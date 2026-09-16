"""Regra de automação da Luz Ambiente Inteligente.

Situação do hardware em setembro/2026: o grupo tem 2 ESP32, um LDR e um LED
comum. Microfone e PIR ainda não chegaram, e a fita RGB também não. Em vez de
jogar fora o desenho da proposta original (luz + som + ocupação), este módulo
mantém as três dimensões, mas hoje só uma está de fato ligada a um sensor
físico:

  * luz (LDR)        -> ATIVA. É o que dirige a decisão agora.
  * som (microfone)  -> DESATIVADA. `main.py` usa um valor fixo enquanto
                         SOM_HABILITADO=false.
  * ocupação (PIR)   -> DESATIVADA. `main.py` considera o ambiente sempre
                         ocupado enquanto OCUPACAO_HABILITADA=false.

Quando o PIR e o microfone chegarem, ativar as flags no backend é suficiente
— nenhuma função aqui precisa mudar. É por isso que a regra continua pura
(sem MQTT, sem banco) e testada por completo, mesmo nas partes ainda inertes.
"""

from dataclasses import dataclass, field

BAIXO = "baixo"
MEDIO = "medio"
ALTO = "alto"

CENA_APAGADA = "apagada"   # sem ocupação (quando o PIR existir)
CENA_CLARO = "claro"       # ocupado, mas já tem luz suficiente — LED apagado
CENA_SUAVE = "suave"
CENA_MEDIA = "media"
CENA_FESTA = "festa"


@dataclass(frozen=True)
class Cena:
    """Estado desejado da iluminação. Vira comando MQTT em `main.py`."""

    nome: str
    brilho: int  # 0-255, já limitado por AUTOMATION_BRILHO_MAX
    cor: tuple[int, int, int]  # usado pelo dashboard e por uma futura fita RGB
    animacao: str  # "off" | "estatica" | "respiracao" | "pulso"
    escuro: bool = False       # memória do Schmitt trigger de luz
    faixa_som: str = BAIXO     # memória do Schmitt trigger de som

    def to_payload(self, source: str) -> dict:
        return {
            "cena": self.nome,
            "brilho": self.brilho,
            "cor": {"r": self.cor[0], "g": self.cor[1], "b": self.cor[2]},
            "animacao": self.animacao,
            "source": source,
        }


@dataclass(frozen=True)
class Config:
    """Parâmetros ajustáveis por `.env`, calibrados em laboratório."""

    limiar_luz: float = 40.0      # % de luminosidade; abaixo disso está escuro
    histerese_luz: float = 8.0
    limiar_medio: float = 25.0    # som (hoje inerte, ver módulo acima)
    limiar_alto: float = 55.0
    histerese_som: float = 6.0
    brilho_max: int = 120
    carencia_presenca_s: float = 120.0  # presença (hoje inerte)
    cores: dict[str, tuple[int, int, int]] = field(
        default_factory=lambda: {
            CENA_SUAVE: (255, 170, 80),   # âmbar quente, leitura/estudo
            CENA_MEDIA: (120, 180, 255),  # azul frio, conversa
            CENA_FESTA: (255, 60, 160),   # magenta, animação
        }
    )


def ambiente_ocupado(
    movimento_agora: bool,
    segundos_desde_movimento: float | None,
    carencia_s: float,
) -> bool:
    """Ocupação = movimento agora OU movimento recente dentro da carência.

    Não usada na decisão enquanto o PIR não existir (`OCUPACAO_HABILITADA`
    em `main.py` força o ambiente a "sempre ocupado"), mas fica pronta e
    testada para quando o sensor chegar.
    """
    if movimento_agora:
        return True
    if segundos_desde_movimento is None:
        return False
    return segundos_desde_movimento <= carencia_s


def classificar_luz(nivel_luz: float, cfg: Config, escuro_atual: bool) -> bool:
    """Schmitt trigger de duas zonas para a leitura do LDR.

    `nivel_luz` é luminosidade em %, onde valor MAIOR significa AMBIENTE MAIS
    CLARO (convenção do projeto-base do professor). Abaixo do limiar está
    escuro; acima do limiar mais a histerese está claro; no meio, mantém o
    estado anterior — é essa zona morta que evita a luz piscando quando a
    leitura do LDR fica oscilando perto do limite.
    """
    if nivel_luz < cfg.limiar_luz:
        return True
    if nivel_luz > cfg.limiar_luz + cfg.histerese_luz:
        return False
    return escuro_atual


def classificar_som(nivel: float, cfg: Config, faixa_atual: str) -> str:
    """Schmitt trigger de três faixas para o som (hoje inerte).

    Subir de faixa exige cruzar o limiar; descer exige cair `histerese_som`
    abaixo dele.
    """
    if faixa_atual == ALTO:
        if nivel < cfg.limiar_alto - cfg.histerese_som:
            faixa_atual = MEDIO
        else:
            return ALTO
    if faixa_atual == MEDIO:
        if nivel >= cfg.limiar_alto:
            return ALTO
        if nivel < cfg.limiar_medio - cfg.histerese_som:
            return BAIXO
        return MEDIO
    # faixa_atual == BAIXO
    if nivel >= cfg.limiar_alto:
        return ALTO
    if nivel >= cfg.limiar_medio:
        return MEDIO
    return BAIXO


def decidir(
    ocupado: bool,
    nivel_luz: float,
    nivel_som: float,
    cfg: Config,
    escuro_atual: bool = False,
    faixa_som_atual: str = BAIXO,
) -> Cena:
    """Combina ocupação, luz ambiente e som na cena desejada.

    Ordem das perguntas, da mais grave para a mais fina:
    1. Tem alguém no ambiente? Se não, apaga — é a regra que justifica o
       projeto (economia de energia), e hoje sempre responde "sim" enquanto
       o PIR não existe.
    2. Já está claro o suficiente sozinho? Se sim, não precisa de LED.
    3. Está escuro: o nível de som (hoje fixo) define a cena.
    """
    if not ocupado:
        return Cena(CENA_APAGADA, 0, (0, 0, 0), "off", escuro_atual, faixa_som_atual)

    escuro = classificar_luz(nivel_luz, cfg, escuro_atual)
    if not escuro:
        return Cena(CENA_CLARO, 0, (0, 0, 0), "off", escuro, faixa_som_atual)

    faixa = classificar_som(nivel_som, cfg, faixa_som_atual)

    if faixa == BAIXO:
        return Cena(
            CENA_SUAVE,
            max(8, int(cfg.brilho_max * 0.25)),
            cfg.cores[CENA_SUAVE],
            "estatica",
            escuro,
            faixa,
        )
    if faixa == MEDIO:
        return Cena(
            CENA_MEDIA,
            int(cfg.brilho_max * 0.6),
            cfg.cores[CENA_MEDIA],
            "respiracao",
            escuro,
            faixa,
        )
    return Cena(
        CENA_FESTA,
        cfg.brilho_max,
        cfg.cores[CENA_FESTA],
        "pulso",
        escuro,
        faixa,
    )
