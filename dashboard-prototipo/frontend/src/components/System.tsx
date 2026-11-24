import { fmtDateTime, fmtNum } from '../format'
import { SCENE_RANGE } from '../scenes'
import type { AppConfig, LiveState } from '../types'
import { Panel, SceneBadge } from './ui'

export function System({ config, live }: { config: AppConfig; live: LiveState }) {
  const fw = config.firmware
  const t = fw.topics
  return (
    <div className="stack">
      <div className="grid g-2">
        <Panel title="Integração MQTT">
          <dl className="kv">
            <dt>Broker</dt><dd className="mono">{config.demo ? 'não usado (modo demonstração)' : `${config.mqtt.host}:${config.mqtt.port}${config.mqtt.tls ? ' (TLS)' : ''}`}</dd>
            <dt>Autenticação</dt><dd>{config.mqtt.auth ? 'configurada no backend' : 'nenhuma (broker local na rede)'}</dd>
            <dt>Assinatura</dt><dd className="mono">{config.mqtt.subscription}</dd>
            <dt>Modo</dt><dd>contrato v1.1: o backend decide e é o único que publica comandos (<code>luzambiente/v1/atuador/+/comando</code>); os tópicos da N1 continuam assinados só para o histórico</dd>
            <dt>Mensagens recebidas</dt><dd className="num">{fmtNum(live.stats.recebidas)} <span className="muted">desde {fmtDateTime(live.started_at)}</span></dd>
            <dt>Inválidas</dt><dd className="num">{fmtNum(live.stats.invalidas)}</dd>
            <dt>Não tratadas</dt><dd className="num">{fmtNum(live.stats.nao_tratadas)}</dd>
            <dt>Erros de processamento</dt><dd className="num">{fmtNum(live.stats.erros)}</dd>
          </dl>
        </Panel>
        <Panel title="Tópicos">
          <div className="table-wrap">
            <table>
              <thead><tr><th>Tópico</th><th>Origem</th><th>Situação</th></tr></thead>
              <tbody>
                <tr><td className="mono small">{t.command}</td><td>sensor → atuador</td><td>ativo · na mudança de cena</td></tr>
                <tr><td className="mono small">{t.actuator_status}</td><td>atuador (retido)</td><td>ativo · após cada comando</td></tr>
                <tr><td className="mono small">{t.optional.sensor_telemetry}</td><td>sensor</td><td>ativo · a cada 2 s</td></tr>
                <tr><td className="mono small">{t.optional.sensor_connection}</td><td>sensor (LWT, retido)</td><td>ativo · presença</td></tr>
                <tr><td className="mono small">{t.optional.actuator_connection}</td><td>atuador (LWT, retido)</td><td>ativo · presença</td></tr>
                <tr><td className="mono small">{t.optional.actuator_shade}</td><td>atuador (retido)</td><td>ativo · posição da sombra</td></tr>
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
      <div className="grid g-2">
        <Panel title="Cenas e LEDs definidos no firmware">
          <div className="table-wrap">
            <table>
              <thead><tr><th>Cena</th><th>Leitura ADC</th><th>LED 1</th><th>LED 2</th><th>LED 3</th><th>LED 4</th></tr></thead>
              <tbody>
                {fw.scenes.map((s) => (
                  <tr key={s.key}>
                    <td><SceneBadge cena={s.key} /></td><td className="num">{SCENE_RANGE[s.key]}</td>
                    {s.leds.map((on, i) => <td key={i}>{on ? 'aceso' : <span className="muted">—</span>}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="note">LED 1 = GPIO{fw.leds[0].gpio}, LED 2 = GPIO{fw.leds[1].gpio}, LED 3 = GPIO{fw.leds[2].gpio}, LED 4 = GPIO{fw.leds[3].gpio}.
            Client IDs dos dispositivos: <code>{fw.device_ids.sensor}</code> e <code>{fw.device_ids.actuator}</code> (o backend usa um ID próprio para não derrubá-los).
            Na cena <i>extrema</i> os quatro LEDs acendem e a sombra fecha.</p>
        </Panel>
        <Panel title="Limitações conhecidas">
          <ul className="small secondary" style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 6 }}>
            <li><b>Limites das cenas sem calibração:</b> 150 / 400 / 1000 vieram do firmware original. Com a luz comum de um quarto o LDR lê ~1.500–1.800, o que já cai em <i>extrema</i>.</li>
            <li>A leitura é o valor bruto do ADC (0–4095), sem conversão para lux; depende do LDR, do resistor de 10 kΩ e da posição do sensor (precisa enxergar a luz).</li>
            <li>A <b>cena</b> só é publicada quando muda; a leitura bruta vai a cada 2 s. Se o atuador estiver desconectado na hora da mudança, ele perde aquele comando (QoS 0, não retido) e só reage na próxima mudança.</li>
            <li>O <b>broker Mosquitto local</b> não tem usuário nem senha e escuta na rede (porta 1883): qualquer dispositivo da mesma rede pode publicar nesses tópicos. Mensagens fora do formato ficam registradas como inválidas.</li>
            <li>Os ESP32 usam o <b>IP fixo do computador</b> que roda o Docker. Se o IP mudar (DHCP), as placas param de conectar até o firmware ser regravado.</li>
            <li>O <b>servo</b> informa a posição <i>comandada</i>; o SG90/MG90S não tem sensor de posição, então um travamento mecânico não é detectado.</li>
            <li>Os horários são os do recebimento no backend; os payloads do firmware não trazem horário.</li>
            <li>O estado dos LEDs é derivado da cena confirmada, não lido dos pinos.</li>
            <li>Os dados só são coletados enquanto o computador, o Docker e as duas placas estão ligados.</li>
          </ul>
        </Panel>
      </div>
      <ServoPanel config={config} live={live} />
    </div>
  )
}

function ServoPanel({ config, live }: { config: AppConfig; live: LiveState }) {
  const s = config.firmware.servo
  const shade = live.actuator.shade
  const closesOn = s.closes_on.map((c) => <SceneBadge key={c} cena={c} />)
  return (
    <Panel title="Servomotor de sombreamento"
      right={shade
        ? <span className={`pill ${shade.estado === 'fechada' ? 'warn' : 'good'}`}>sombra {shade.estado}{shade.graus != null ? ` · ${shade.graus}°` : ''}</span>
        : <span className="pill">sem posição publicada</span>}>
      <div className="grid g-2">
        <dl className="kv">
          <dt>Situação</dt><dd>lógica pronta no firmware · {s.hardware}</dd>
          <dt>Pino de sinal</dt><dd className="mono">GPIO{s.gpio}</dd>
          <dt>Sombra aberta</dt><dd className="num">{s.open_deg}° <span className="muted">(posição padrão)</span></dd>
          <dt>Sombra fechada</dt><dd className="num">{s.closed_deg}°</dd>
          <dt>Fecha na cena</dt><dd className="row" style={{ gap: 6 }}>{closesOn}<span className="muted small">· abre nas demais</span></dd>
          <dt>Movimento</dt><dd>suave, {s.step_deg}° a cada {s.step_ms} ms</dd>
          <dt>Em repouso</dt><dd>{s.holds_position ? 'segura a posição (PWM ligado)' : 'motor solto (PWM desligado após mover)'}</dd>
          <dt>Alimentação</dt><dd>{s.power}</dd>
        </dl>
        <div>
          <dl className="kv">
            <dt>Última posição</dt>
            <dd>{shade ? <><b>{shade.estado}</b>{shade.graus != null ? ` (${shade.graus}°)` : ''}</> : <span className="muted">nenhuma ainda</span>}</dd>
            <dt>Recebida em</dt>
            <dd>{shade ? `${fmtDateTime(shade.at)}${shade.retained ? ' · retida no broker' : ''}` : '—'}</dd>
            <dt>Tópico</dt><dd className="mono small">{config.firmware.topics.optional.actuator_shade}</dd>
          </dl>
          <p className="note">
            O atuador publica a posição <b>comandada</b> ao conectar e depois de cada movimento; o histórico fica na tabela <code>shade_events</code>.
            Com o servo desconectado, a posição continua sendo publicada normalmente. Ao instalar o servo novo, recalibre os ângulos com folga das pontas (0° e 180°)
            e confirme que o braço não encosta em nada: travado, o servo aquece e queima.
          </p>
        </div>
      </div>
    </Panel>
  )
}
