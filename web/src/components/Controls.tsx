import { useState } from "react";
import type { RunOptions } from "../api";

interface Props {
  running: boolean;
  onRun: (opts: RunOptions) => void;
}

export function Controls({ running, onRun }: Props) {
  const [seed, setSeed] = useState(1);
  const [hardRate, setHardRate] = useState(0);
  const [halt, setHalt] = useState(false);

  return (
    <div className="controls">
      <label>
        seed
        <input
          type="number"
          value={seed}
          onChange={(e) => setSeed(Number(e.target.value))}
        />
      </label>
      <label>
        incubator fault rate: <strong>{hardRate.toFixed(2)}</strong>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={hardRate}
          onChange={(e) => setHardRate(Number(e.target.value))}
        />
      </label>
      <label className="checkbox">
        <input type="checkbox" checked={halt} onChange={(e) => setHalt(e.target.checked)} />
        halt on failure
      </label>
      <button
        className="run"
        disabled={running}
        onClick={() => onRun({ seed, hardRate, halt, delay: 0.18 })}
      >
        {running ? "running…" : "▶ run workflow"}
      </button>
    </div>
  );
}
