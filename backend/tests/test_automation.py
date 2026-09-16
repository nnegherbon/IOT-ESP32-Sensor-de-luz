from app.automation import (
    ALTO,
    BAIXO,
    CENA_APAGADA,
    CENA_CLARO,
    CENA_FESTA,
    CENA_MEDIA,
    CENA_SUAVE,
    MEDIO,
    Config,
    ambiente_ocupado,
    classificar_luz,
    classificar_som,
    decidir,
)

CFG = Config(
    limiar_luz=40,
    histerese_luz=8,
    limiar_medio=25,
    limiar_alto=55,
    histerese_som=6,
    brilho_max=120,
    carencia_presenca_s=120,
)


# --- luz (LDR) — o sensor que hoje existe de verdade -----------------------


def test_luz_baixa_fica_escuro():
    assert classificar_luz(10, CFG, escuro_atual=False) is True


def test_luz_alta_fica_claro():
    assert classificar_luz(90, CFG, escuro_atual=True) is False


def test_zona_morta_mantem_escuro():
    # 45 está entre o limiar (40) e o limiar+histerese (48): mantém o estado.
    assert classificar_luz(45, CFG, escuro_atual=True) is True


def test_zona_morta_mantem_claro():
    assert classificar_luz(45, CFG, escuro_atual=False) is False


def test_cruzar_o_teto_da_histerese_libera_o_claro():
    assert classificar_luz(49, CFG, escuro_atual=True) is False


def test_cair_abaixo_do_limiar_forca_escuro_mesmo_vindo_de_claro():
    assert classificar_luz(39, CFG, escuro_atual=False) is True


# --- ocupação (PIR) — hoje inerte, mas testada para quando existir --------


def test_movimento_agora_significa_ocupado():
    assert ambiente_ocupado(True, None, 120) is True


def test_sem_movimento_nunca_visto_significa_vazio():
    assert ambiente_ocupado(False, None, 120) is False


def test_pessoa_parada_continua_ocupando_dentro_da_carencia():
    assert ambiente_ocupado(False, 60, 120) is True


def test_carencia_expira_e_ambiente_fica_vazio():
    assert ambiente_ocupado(False, 121, 120) is False


# --- som (microfone) — hoje inerte, mas testada para quando existir ------


def test_som_baixo_fica_na_faixa_baixa():
    assert classificar_som(10, CFG, BAIXO) == BAIXO


def test_som_sobe_para_media_no_limiar():
    assert classificar_som(25, CFG, BAIXO) == MEDIO


def test_som_sobe_para_alta_no_limiar():
    assert classificar_som(55, CFG, MEDIO) == ALTO


def test_histerese_do_som_segura_a_faixa_na_descida():
    assert classificar_som(51, CFG, ALTO) == ALTO
    assert classificar_som(48, CFG, ALTO) == MEDIO


# --- decisão completa -------------------------------------------------------


def test_sem_ocupacao_apaga_mesmo_no_escuro():
    # Hoje isso nunca acontece de verdade (ocupado é sempre True sem PIR),
    # mas a regra continua correta para quando o sensor existir.
    cena = decidir(False, nivel_luz=5, nivel_som=90, cfg=CFG)
    assert cena.nome == CENA_APAGADA
    assert cena.brilho == 0


def test_ocupado_e_claro_apaga_o_led():
    # É o caso comum de hoje: ambiente sempre "ocupado", luz do dia acesa.
    cena = decidir(True, nivel_luz=80, nivel_som=0, cfg=CFG)
    assert cena.nome == CENA_CLARO
    assert cena.brilho == 0
    assert cena.animacao == "off"


def test_ocupado_e_escuro_com_som_padrao_acende_suave():
    # É o outro caso comum de hoje: escureceu, som ainda desativado (fixo em
    # 0 = faixa baixa) -> cena "suave".
    cena = decidir(True, nivel_luz=10, nivel_som=0, cfg=CFG)
    assert cena.nome == CENA_SUAVE
    assert cena.animacao == "estatica"
    assert 0 < cena.brilho < CFG.brilho_max


def test_escuro_com_som_medio_da_cena_media():
    # Continua funcionando assim que SOM_HABILITADO=true no backend.
    cena = decidir(True, nivel_luz=10, nivel_som=30, cfg=CFG)
    assert cena.nome == CENA_MEDIA
    assert cena.animacao == "respiracao"


def test_escuro_com_som_alto_da_cena_festa_no_brilho_maximo():
    cena = decidir(True, nivel_luz=10, nivel_som=80, cfg=CFG)
    assert cena.nome == CENA_FESTA
    assert cena.brilho == CFG.brilho_max
    assert cena.animacao == "pulso"


def test_estado_de_luz_e_som_persiste_entre_chamadas():
    # main.py guarda escuro/faixa_som em `state` e repassa a cada chamada;
    # aqui simulamos isso manualmente.
    cena1 = decidir(True, nivel_luz=44, nivel_som=0, cfg=CFG, escuro_atual=True)
    assert cena1.escuro is True  # 44 está na zona morta, mantém escuro
    cena2 = decidir(True, nivel_luz=44, nivel_som=0, cfg=CFG, escuro_atual=cena1.escuro)
    assert cena2.nome == CENA_SUAVE


def test_brilho_nunca_passa_do_teto_configurado():
    for nivel_som in range(0, 101, 5):
        assert decidir(True, 10, nivel_som, CFG).brilho <= CFG.brilho_max


def test_payload_do_comando_tem_o_contrato_esperado():
    payload = decidir(True, nivel_luz=10, nivel_som=80, cfg=CFG).to_payload("automation")
    assert set(payload) == {"cena", "brilho", "cor", "animacao", "source"}
    assert set(payload["cor"]) == {"r", "g", "b"}
    assert payload["source"] == "automation"
