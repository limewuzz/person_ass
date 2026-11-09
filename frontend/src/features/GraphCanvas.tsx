import { useQuery } from "@tanstack/react-query";
import { readCatalog } from "../app/catalog";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Pause, Play, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
export function GraphCanvas() {
  const nodesQuery = useQuery({
    queryKey: ["graphnodes"],
    queryFn: () => readCatalog.nodes(),
  });
  const nodeHref = (role: string) => {
    const node = nodesQuery.data?.items.find((n) => n.role === role);
    return node ? `/nodes/${encodeURIComponent(node.id)}` : "/nodes";
  };
  const [scene, setScene] = useState("normal"),
    [playing, setPlaying] = useState(
      !matchMedia("(prefers-reduced-motion: reduce)").matches,
    ),
    [step, setStep] = useState(0),
    [speed, setSpeed] = useState(1),
    [zoom, setZoom] = useState(1),
    [visible, setVisible] = useState(true);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const obs = new IntersectionObserver(([entry]) =>
      setVisible(entry.isIntersecting),
    );
    if (root.current) obs.observe(root.current);
    return () => obs.disconnect();
  }, []);
  useEffect(() => {
    const svg = root.current?.querySelector("svg");
    const update = () => {
      if (!playing || !visible || document.hidden) svg?.pauseAnimations();
      else svg?.unpauseAnimations();
    };
    update();
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, [playing, visible]);
  useEffect(() => {
    if (!playing || !visible) return;
    const timer = setInterval(() => {
      if (!document.hidden) setStep((s) => (s + 1) % 4);
    }, 1800 / speed);
    return () => clearInterval(timer);
  }, [playing, speed, visible]);
  const stages =
    scene === "normal"
      ? ["请求进入", "策略与审批", "Worker 领取", "模拟结果"]
      : scene === "outage"
        ? ["主控不可用", "写操作暂停", "Mac 缓存只读", "等待恢复"]
        : ["主控恢复", "补齐事件游标", "校验状态", "完成对账"];
  return (
    <section className="graph-panel" ref={root}>
      <div className="canvas-head">
        <span>
          ◈ 架构与执行路径 <small>LOCAL MOCK · 设计拓扑</small>
        </span>
        <div className="scene-tabs">
          {[
            ["normal", "正常流程"],
            ["outage", "主控故障"],
            ["recovery", "恢复对账"],
          ].map(([s, l]) => (
            <button
              key={s}
              aria-pressed={s === scene}
              onClick={() => {
                setScene(s);
                setStep(0);
              }}
            >
              {l}
            </button>
          ))}
        </div>
      </div>
      <div className="graph-scroll">
        <div
          className={`graph scene-${scene} ${playing && visible ? "playing" : ""}`}
          style={{ minWidth: 660 * zoom }}
        >
          <div className="graph-grid" />
          <svg
            viewBox="0 0 900 450"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <path
              className="wire cyan"
              d="M450 65 V200 M450 260 L730 230 M450 260 L160 230 M450 270 V385"
            />
            <path className="wire purple" d="M730 250 V385 H490" />
            <circle className="packet" r="4">
              <animateMotion
                dur={`${5 / speed}s`}
                repeatCount="indefinite"
                path="M450 65 V200 L730 230 V385 H490"
              />
            </circle>
          </svg>
          <div className="graph-orbit" />
          <Link className="graph-node ingress" to="/integrations">
            <small>多入口 · INGRESS</small>
            <b>Web / Android / CLI</b>
            <span>统一入口 · 未连接生产</span>
          </Link>
          <Link
            className={`graph-node us ${scene === "outage" ? "down" : ""}`}
            to={nodeHref("PRIMARY")}
          >
            <small>PRIMARY · 唯一写主控</small>
            <b>美国控制平面</b>
            <span>
              {scene === "outage"
                ? "模拟 OFFLINE · 写入暂停"
                : "任务 · 策略 · 审计账本"}
            </span>
            <em>MOCK / UNKNOWN</em>
          </Link>
          <Link className="graph-node relay" to={nodeHref("RELAY")}>
            <small>RELAY</small>
            <b>UCloud</b>
            <span>保留原中继职责</span>
          </Link>
          <Link className="graph-node mac" to={nodeHref("STANDBY_GATEWAY")}>
            <small>STANDBY + WORKER</small>
            <b>Mac mini</b>
            <span>只读备用 · 不提升写权限</span>
          </Link>
          <Link
            className="graph-node tencent"
            to={nodeHref("EXISTING_BUSINESS")}
          >
            <small>EXISTING BUSINESS</small>
            <b>腾讯云</b>
            <span>既有业务冻结</span>
          </Link>
          <span className="graph-note">虚线 = 设计关系 · 没有连通性证据</span>
        </div>
      </div>
      <div className="graph-controls">
        <button
          aria-label={playing ? "暂停动画" : "播放动画"}
          onClick={() => setPlaying(!playing)}
        >
          {playing ? <Pause size={14} /> : <Play size={14} />}
        </button>
        <button aria-label="重放动画" onClick={() => setStep(0)}>
          <RotateCcw size={14} />
        </button>
        <select
          aria-label="动画速度"
          value={speed}
          onChange={(e) => setSpeed(Number(e.target.value))}
        >
          <option value={1}>1×</option>
          <option value={2}>2×</option>
        </select>
        <button
          aria-label="缩小拓扑"
          onClick={() => setZoom(Math.max(1, zoom - 0.2))}
        >
          <ZoomOut size={14} />
        </button>
        <button
          aria-label="放大拓扑"
          onClick={() => setZoom(Math.min(1.6, zoom + 0.2))}
        >
          <ZoomIn size={14} />
        </button>
        <span>模拟阶段 {step + 1}/4</span>
      </div>
      <div className="stages">
        {stages.map((s, i) => (
          <div className={i === step ? "current" : ""} key={s}>
            <small>0{i + 1}</small>
            <strong>{s}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}
