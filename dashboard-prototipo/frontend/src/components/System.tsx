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
            <dt>Autenticação</dt><dd>{config.mqtt.auth ? 'configurada no backend' : 'nenhuma (broker público)'}</dd>
            <dt>Assinatura</dt><dd className="mono">{config.mqtt.subscription}</dd>
            <dt>Modo</dt><dd>somente leitura — o backend nunca publica</dd>
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
                <tr><td className="mono small">{t.command}</td><td>sensor → atuador</td><td>firmware original</td></tr>
                <tr><td className="mono small">{t.actuator_status}</td><td>atuador (retido)</td><td>firmware original</td></tr>
                <tr><td className="mono small">{t.optional.sensor_telemetry}</td><td>sensor</td><td className="muted">opcional (patch)</td></tr>
                <tr><td className="mono small">{t.optional.sensor_connection}</td><td>sensor (LWT)</td><td className="muted">opcional (patch)</td></tr>
                <tr><td className="mono small">{t.optional.actuator_connection}</td><td>atuador (LWT)</td><td className="muted">opcional (patch)</td></tr>
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
            Client IDs dos dispositivos: <code>{fw.device_ids.sensor}</code> e <code>{fw.device_ids.actuator}</code> (o backend usa um ID próprio para não derrubá-los).</p>
        </Panel>
        <Panel title="Limitações conhecidas">
          <ul className="small secondary" style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 6 }}>
            <li>O firmware original não publica a leitura analógica do LDR; leituras, mín/máx/média e alertas por limite exigem o patch opcional do sensor.</li>
            <li>O sensor publica apenas quando a cena muda. Sem mensagens novas não significa necessariamente desconexão.</li>
            <li>Nenhum dos ESP32 publica presença/LWT no firmware original, então online/offline só é detectado com o patch.</li>
            <li>Os timestamps são os do recebimento no backend; os payloads do firmware não trazem horário.</li>
            <li>O estado dos LEDs é derivado da cena confirmada, não lido dos pinos.</li>
            <li>O broker público <code>broker.hivemq.com</code> aceita publicações de qualquer cliente nesses tópicos; mensagens fora do formato ficam registradas como inválidas.</li>
          </ul>
        </Panel>
      </div>
      <Panel title="Servomotor de sombreamento" right={<span className="pill">não implementado no firmware</span>}>
        <p className="small secondary" style={{ margin: 0 }}>
          O README descreve o servomotor como em desenvolvimento. O banco já possui a tabela <code>shade_events</code> (comando, posição, confirmação)
          e mensagens em qualquer tópico sob <code>iot/luzambiente/</code> são guardadas como "não tratadas", prontas para um novo interpretador
          quando o formato for definido. Nada é exibido como existente até lá.
        </p>
      </Panel>
    </div>
  )
}
