import type { DeviceView } from "../types";

const KIND: Record<string, string> = {
  lh1: "liquid handler · serial",
  reader1: "plate reader · TCP",
  inc1: "incubator · TCP",
};

export function DevicePanel({ devices }: { devices: DeviceView[] }) {
  return (
    <section className="panel">
      <h2>Work cell</h2>
      <div className="devices">
        {devices.map((d) => (
          <div key={d.name} className={`device ${d.health}`}>
            <div className="device-head">
              <span className="device-name">{d.name}</span>
              <span className={`badge ${d.health}`}>{d.health}</span>
            </div>
            <div className="device-kind">{KIND[d.name] ?? ""}</div>
            <div className="device-stats">
              <span>errors {d.errors}</span>
              <span>retries {d.retries}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
