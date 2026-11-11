import { useRef, useState, type FormEvent } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowDown,
  ArrowRight,
  BookOpen,
  Check,
  CheckCheck,
  ChevronRight,
  Command,
  ExternalLink,
  FileText,
  GitBranch,
  Layers3,
  MessageCircle,
  Plus,
  Search,
  Sparkles,
  Terminal,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  recipeHref,
  storePortalDraft,
  workshopBase,
  type RecipeId,
} from "../src/workspace/portal-handoff";
import "./portal.css";
const base = workshopBase(
  import.meta.env.VITE_WORKSHOP_BASE ??
    (import.meta.env.DEV ? "/" : "/workshop/"),
);
const scenarios: {
  id: RecipeId;
  number: string;
  title: string;
  verb: string;
  copy: string;
  chain: string[];
  icon: LucideIcon;
  accent: string;
}[] = [
  {
    id: "paper",
    number: "01",
    title: "把论文读成下一步",
    verb: "论文研究",
    copy: "从一份笔记出发，整理方法、归档资料，为下一次实验留好起点。",
    chain: ["摘要与笔记", "知识归档", "实验立项"],
    icon: BookOpen,
    accent: "sage",
  },
  {
    id: "decision",
    number: "02",
    title: "让讨论落到行动",
    verb: "方案开发",
    copy: "把已经想清楚的方案，变成有上下文、有负责人、有结果的工作。",
    chain: ["记录决策", "开发任务", "进度回执"],
    icon: GitBranch,
    accent: "peach",
  },
  {
    id: "wechat",
    number: "03",
    title: "随手记，也能认真办",
    verb: "日常交办",
    copy: "先接住一个想法，再补齐背景、安排提醒，让琐事有处可去。",
    chain: ["整理上下文", "建立待办", "结果通知"],
    icon: MessageCircle,
    accent: "lavender",
  },
  {
    id: "checkpoint",
    number: "04",
    title: "给每次实验留个坐标",
    verb: "算力实验",
    copy: "关联检查点、指标与产物引用，把一次实验的过程和结果放在一起。",
    chain: ["检查点引用", "实验记录", "异常通知"],
    icon: Layers3,
    accent: "sky",
  },
];
const tools = [
  {
    title: "AmazingWork",
    tag: "聊模型 · 写内容",
    description: "继续使用现有的聊天、文件和个人模型工作台。",
    href: "/chat/",
    icon: MessageCircle,
    mark: "A",
  },
  {
    title: "Agent Space",
    tag: "官网与 CLI 工作台",
    description: "从原有入口进入独立的 AI 网页和终端会话。",
    href: "/agent",
    icon: Terminal,
    mark: ">_",
  },
  {
    title: "模型与额度",
    tag: "原站工具",
    description: "查看模型下载目录，或打开已有的模型额度页面。",
    href: "/models",
    secondary: "/usage/",
    icon: Layers3,
    mark: "◈",
  },
];
function App() {
  const [input, setInput] = useState(""),
    [recipe, setRecipe] = useState<RecipeId>("paper"),
    [error, setError] = useState(""),
    [query, setQuery] = useState(""),
    [searchOpen, setSearchOpen] = useState(false);
  const composer = useRef<HTMLTextAreaElement>(null),
    search = useRef<HTMLDialogElement>(null);
  function submit(event: FormEvent) {
    event.preventDefault();
    let saved = false;
    try {
      saved = storePortalDraft(window.sessionStorage, recipe, input);
    } catch {
      /* Storage can be disabled by browser policy. */
    }
    if (!saved) {
      setError("草稿未能保存。请复制内容，在工作坊里继续。");
      return;
    }
    window.location.assign(recipeHref(base, recipe));
  }
  function choose(id: RecipeId) {
    setRecipe(id);
    document.getElementById("start")?.scrollIntoView({
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
      block: "center",
    });
    composer.current?.focus({ preventScroll: true });
  }
  const searchItems = [
    { title: "我的工作坊", detail: "任务、审批与结果", href: base },
    ...scenarios.map((s) => ({
      title: s.verb,
      detail: s.title,
      href: recipeHref(base, s.id),
    })),
    ...tools.flatMap((t) => [
      {
        title: t.secondary ? "模型下载目录" : t.title,
        detail: t.tag,
        href: t.href,
      },
      ...(t.secondary
        ? [{ title: "模型额度雷达", detail: "原站额度页面", href: t.secondary }]
        : []),
    ]),
  ].filter((t) =>
    (t.title + t.detail).toLowerCase().includes(query.trim().toLowerCase()),
  );
  return (
    <>
      <a className="skip" href="#main">
        跳到主要内容
      </a>
      <header className="site-header">
        <a className="brand" href="/" aria-label="MagicWorkshop 首页">
          <span className="brand-mark">
            m<span>✦</span>
          </span>
          <span>
            <strong>MagicWorkshop</strong>
            <small>你的个人工作坊</small>
          </span>
        </a>
        <nav aria-label="主导航">
          <a href="#scenarios">从场景开始</a>
          <a href="#spaces">我的工具</a>
          <button
            className="search-trigger"
            onClick={() => {
              setSearchOpen(true);
              search.current?.showModal();
            }}
            aria-label="搜索入口"
          >
            <Search size={17} />
            <span>找一个入口</span>
            <kbd>⌕</kbd>
          </button>
        </nav>
        <a className="header-work" href={base}>
          进入工作坊 <ArrowRight size={16} />
        </a>
      </header>
      <main id="main">
        <section className="hero">
          <div className="hero-copy">
            <div className="eyebrow">
              <span /> A LITTLE SPACE FOR BIG IDEAS
            </div>
            <h1>
              想法很多，
              <br />
              一起把事情<em>做好。</em>
            </h1>
            <p className="hero-intro">
              你的研究、方案和日常交办，
              <br className="desktop-break" />
              在一个安静的工作坊里，有条理地往前走。
            </p>
            <div className="hero-actions">
              <a className="primary" href="#start">
                开始一件新工作 <Plus size={18} />
              </a>
              <a className="text-link" href="#scenarios">
                看看可以做什么 <ArrowDown size={16} />
              </a>
            </div>
            <p className="hero-note">
              <CheckCheck size={15} /> 先整理意图，再检查授权，每一步都有去处。
            </p>
          </div>
          <div className="hero-board" aria-label="工作流示例">
            <div className="board-top">
              <span className="board-logo">
                <Sparkles size={17} /> 一件事，慢慢成形
              </span>
              <span className="board-label">工作流示例</span>
            </div>
            <div className="board-note">
              <FileText size={22} />
              <div>
                <small>一个新的想法</small>
                <strong>把这份论文笔记，变成一次实验。</strong>
              </div>
              <span className="note-fold" />
            </div>
            <div className="board-connector">
              <span />
              <ChevronRight size={14} />
            </div>
            <div className="board-steps">
              <div>
                <span className="step-icon">
                  <BookOpen size={18} />
                </span>
                <span>
                  <strong>整理与归档</strong>
                  <small>方法、笔记与知识引用</small>
                </span>
              </div>
              <div>
                <span className="step-icon warm">
                  <GitBranch size={18} />
                </span>
                <span>
                  <strong>检查并安排</strong>
                  <small>明确下一步与所需授权</small>
                </span>
              </div>
              <div>
                <span className="step-icon lilac">
                  <CheckCheck size={18} />
                </span>
                <span>
                  <strong>收好结果</strong>
                  <small>回执、产物与过程记录</small>
                </span>
              </div>
            </div>
            <div className="board-bottom">
              <span>一个工作项，关联每条分支</span>
              <span className="board-stamp">WITH INTENTION</span>
            </div>
          </div>
        </section>
        <section
          id="start"
          className="composer-section"
          aria-labelledby="composer-title"
        >
          <div>
            <span className="eyebrow">MAKE ROOM FOR YOUR NEXT STEP</span>
            <h2 id="composer-title">这次，想推进什么？</h2>
            <p>写下一个念头，带着草稿进入工作坊检查并发起。</p>
          </div>
          <form onSubmit={submit} className="intent-form">
            <label className="sr-only" htmlFor="portal-intent">
              这次想推进的工作
            </label>
            <textarea
              id="portal-intent"
              ref={composer}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              maxLength={4000}
              rows={3}
              placeholder="例如：整理刚读完的论文，归档笔记，再安排一次复现实验…"
            />
            <div className="intent-bottom">
              <div
                className="intent-recipes"
                role="group"
                aria-label="选择工作类型"
              >
                {scenarios.map((s) => (
                  <button
                    type="button"
                    key={s.id}
                    aria-pressed={recipe === s.id}
                    onClick={() => setRecipe(s.id)}
                  >
                    {recipe === s.id && <Check size={12} />} {s.verb}
                  </button>
                ))}
              </div>
              <button
                type="submit"
                className="primary"
                disabled={!input.trim()}
              >
                到工作坊检查 <ArrowRight size={17} />
              </button>
            </div>
            <small className="draft-note">
              此处只保存草稿，不会直接调用模型或启动任务。
            </small>
            {error && (
              <p role="alert" className="form-error">
                {error} <a href={base}>打开工作坊</a>
              </p>
            )}
          </form>
        </section>
        <section
          id="scenarios"
          className="scenarios"
          aria-labelledby="scenarios-title"
        >
          <div className="section-heading">
            <div>
              <span className="eyebrow">FROM AN IDEA TO SOMETHING REAL</span>
              <h2 id="scenarios-title">从你熟悉的一件事开始</h2>
            </div>
            <p>
              不必先想清所有步骤。
              <br />
              选一个场景，让下一步更清楚。
            </p>
          </div>
          <div className="scenario-grid">
            {scenarios.map((s) => (
              <article className={`scenario ${s.accent}`} key={s.id}>
                <div className="scenario-top">
                  <span className="scenario-icon">
                    <s.icon size={23} />
                  </span>
                  <small>{s.number}</small>
                </div>
                <h3>{s.title}</h3>
                <p>{s.copy}</p>
                <div className="scenario-chain">
                  {s.chain.map((c, i) => (
                    <span key={c}>
                      {i > 0 && <ChevronRight size={11} />} {c}
                    </span>
                  ))}
                </div>
                <button
                  className="scenario-action"
                  onClick={() => choose(s.id)}
                >
                  从{s.verb}开始 <ArrowRight size={16} />
                </button>
              </article>
            ))}
          </div>
        </section>
        <section id="spaces" className="tools" aria-labelledby="tools-title">
          <div className="section-heading">
            <div>
              <span className="eyebrow">YOUR FAMILIAR PLACES</span>
              <h2 id="tools-title">熟悉的工具，还在这里</h2>
            </div>
            <p>
              保留各自擅长的事，
              <br />
              从同一个入口出发。
            </p>
          </div>
          <div className="tools-grid">
            {tools.map((t) => (
              <article className="tool" key={t.title}>
                <span className="tool-mark">{t.mark}</span>
                <div>
                  <small>{t.tag}</small>
                  <h3>{t.title}</h3>
                  <p>{t.description}</p>
                </div>
                <div className="tool-actions">
                  <a href={t.href}>
                    打开原有入口 <ExternalLink size={14} />
                  </a>
                  {t.secondary && (
                    <a href={t.secondary}>
                      查看额度 <ExternalLink size={14} />
                    </a>
                  )}
                </div>
              </article>
            ))}
          </div>
          <div className="workshop-link">
            <span className="workshop-link-icon">
              <Command size={23} />
            </span>
            <div>
              <strong>工作项、审批、结果，在同一张桌上。</strong>
              <p>进入工作坊查看自己的工作记录与协同分支。</p>
            </div>
            <a href={base}>
              打开我的工作坊 <ArrowRight size={17} />
            </a>
          </div>
        </section>
        <section className="closing">
          <span className="closing-spark">✦</span>
          <h2>
            留一点空间，
            <br />
            给真正想做的事。
          </h2>
          <a className="text-link" href="#start">
            从一个小想法开始 <ArrowRight size={16} />
          </a>
        </section>
      </main>
      <footer className="footer">
        <a className="footer-brand" href="/">
          MagicWorkshop
        </a>
        <span>个人研究与创作的工作空间</span>
        <a href={base}>
          进入工作坊 <ArrowRight size={14} />
        </a>
      </footer>
      <dialog
        ref={search}
        className="search-dialog"
        onClose={() => setSearchOpen(false)}
        aria-label="搜索工作入口"
      >
        <div className="search-box">
          <Search size={20} />
          <input
            autoFocus={searchOpen}
            aria-label="搜索工作入口"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索论文、工作坊、聊天、模型…"
          />
          <button onClick={() => search.current?.close()} aria-label="关闭搜索">
            <X size={19} />
          </button>
        </div>
        <div className="search-results">
          {searchItems.map((s) => (
            <a href={s.href} key={s.title}>
              <span>
                <strong>{s.title}</strong>
                <small>{s.detail}</small>
              </span>
              <ArrowRight size={16} />
            </a>
          ))}
          {!searchItems.length && <p>没有找到匹配的入口。</p>}
        </div>
      </dialog>
    </>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
