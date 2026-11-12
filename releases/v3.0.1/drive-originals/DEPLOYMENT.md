# MagicWorkshop v3.0.1 — 本机部署运行手册

> 适用范围：把 v3.0.1 部署到一台 Debian/Ubuntu 机器，并可选地开放到公网。
> 本文所有数字均来自 2026-11-11 的一次真实部署执行，不是设计推演。
> 状态：`IMPLEMENTED=YES / TESTED=YES (LOCAL) / DEPLOYED=YES (本机) / APPROVED=LOCAL_ONLY`

## 1. 目标环境与实测基线

| 项 | 实测值 |
|---|---|
| OS | Debian GNU/Linux 12 (bookworm), x86_64 |
| CPU / 磁盘 | 2 vCPU / 45 GiB 可用 |
| Node | v24.22.2（官网 linux-x64 tarball，非 apt 的 18.20.4） |
| npm | 11.19.1 |
| Python | 3.11.2（venv），CI 用 3.12，本机验证通过 |
| 常驻内存 | 102.8 MiB（systemd `MemoryCurrent`=107,782,144 B） |

CI 固定 Node 24 / Python 3.12。本机用 Python 3.11 跑通全部后端测试，说明未依赖 3.12 语法，但**不构成 3.12 之外的兼容性证明**。

## 2. 从零部署

```sh
# 1) 基础工具（Debian 12 自带 nodejs 18 太旧，装官方 tarball）
sudo apt-get update && sudo apt-get install -y git unzip ca-certificates python3-pip python3-venv
V=$(curl -sS https://nodejs.org/dist/index.json | python3 -c "import sys,json;d=json.load(sys.stdin);print([x['version'] for x in d if x['version'].startswith('v24.')][0])")
curl -sSL -o /tmp/node.tar.xz "https://nodejs.org/dist/${V}/node-${V}-linux-x64.tar.xz"
mkdir -p ~/.local && tar -xJf /tmp/node.tar.xz -C ~/.local && mv ~/.local/node-${V}-linux-x64 ~/.local/node
echo 'export PATH="$HOME/.local/node/bin:$PATH"' >> ~/.bashrc && export PATH="$HOME/.local/node/bin:$PATH"

# 2) 取源码（v3.0.1 打在本仓库 tag 上）
git clone --branch v3.0.1 --single-branch https://github.com/limewuzz/person_ass.git dev-v3
cd dev-v3 && git rev-parse HEAD HEAD^{tree}   # 应为 2fa330f7... / ced979dc...

# 3) 依赖
python3 -m venv .venv
.venv/bin/pip install -q -r backend/requirements.lock
npm ci --prefix frontend

# 4) 校验与构建
export MW_PYTHON="$PWD/.venv/bin/python"
node scripts/mw.mjs contract        # 89 paths / 106 operations
node scripts/mw.mjs build           # frontend/dist

# 5) 启动（loopback: 8127 API / 8128 BFF / 5174 静态+会话）
node scripts/mw.mjs start --static
node scripts/mw.mjs stop            # 只停本仓库拥有的进程组
```

访问 `http://127.0.0.1:5174`。

## 3. 登录机制（重要）

前端没有账号密码。会话由 BFF 的引导接口建立：

```
POST /local/session          # 唯一"登录"，只需 Origin 头匹配
  -> 200 {mode: LOCAL_MOCK, csrf, identity: "Ephemeral local integration actor"}
  -> Set-Cookie: mw_local_session=...; HttpOnly; SameSite=Strict
```

之后所有 `/api/*` 由 BFF 在服务端注入合成 Bearer token，浏览器拿不到。

**安全含义：`/local/session` 不校验任何凭据。** 谁能访问该端口，谁就获得 admin（8 个 scope）。这是 LOCAL_MOCK 的设计前提，不是缺陷——但它决定了**绝不能把 5174 直接暴露到公网**。

## 4. 常驻化（systemd）

`deploy/magicworkshop-v3.service`：

```ini
[Unit]
Description=MagicWorkshop v3 local control plane (loopback only)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=<你的用户>
WorkingDirectory=<仓库绝对路径>
Environment=PATH=<node bin>:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=MW_PYTHON=<仓库绝对路径>/.venv/bin/python
ExecStart=<node> scripts/mw.mjs start --static
ExecStop=<node> scripts/mw.mjs stop
TimeoutStartSec=240
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
```

```sh
sudo cp deploy/magicworkshop-v3.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now magicworkshop-v3
sudo systemctl status magicworkshop-v3
```

用 `Type=oneshot + RemainAfterExit=yes`，因为 `mw.mjs start` 自己 daemonize 并记录进程组；用 `forkserver` 会让 systemd 重复接管。

## 5. 公网暴露（可选，需自备认证）

应用只监听 loopback，公网面交给反向代理。**关键约束：应用同时校验 `Host` 和 `Origin` 必须精确等于 `127.0.0.1:5174`（见 `frontend/integration/static_server.mjs:30` 与 `local_stack.py:57`），反代必须重写这两个头，否则一律 403。**

`deploy/magicworkshop-public.nginx.conf` 提供完整配置，要点：

- 80 → 301 跳 HTTPS（Basic Auth 口令不允许明文过网）
- 443 → Basic Auth + TLS，反代到 `127.0.0.1:5174`
- `proxy_set_header Host 127.0.0.1:5174;`
- `proxy_set_header Origin http://127.0.0.1:5174;`
- `proxy_buffering off;` + `proxy_read_timeout 3600s;`（SSE 必须，否则 `/events` 与 `/fanouts/{id}/stream` 会被缓冲挂死）

```sh
sudo apt-get install -y nginx openssl apache2-utils
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout /etc/nginx/ssl/mw-selfsigned.key -out /etc/nginx/ssl/mw-selfsigned.crt \
  -subj "/CN=<公网IP>" -addext "subjectAltName=IP:<公网IP>"
htpasswd -bc /tmp/mw.htpasswd mw '<强口令>'
sudo install -o root -g www-data -m 640 /tmp/mw.htpasswd /etc/nginx/.mw-htpasswd && rm -f /tmp/mw.htpasswd
sudo cp deploy/magicworkshop-public.nginx.conf /etc/nginx/sites-available/magicworkshop
sudo ln -sf /etc/nginx/sites-available/magicworkshop /etc/nginx/sites-enabled/magicworkshop
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

云厂商防火墙另需放行 `tcp:80,tcp:443`。GCP 上从机器内部**改不了**（默认服务账号只有 `devstorage.read_only` 类 scope，`gcloud compute` 会报 `insufficient authentication scopes`），必须在控制台或具备 `compute.securityAdmin` 的账号上执行。

## 6. 验收命令

```sh
curl -sS http://127.0.0.1:8127/api/v1/health/live
curl -sS -o /dev/null -w '%{http_code}\n' -X POST -H 'Origin: http://127.0.0.1:5174' http://127.0.0.1:5174/local/session
curl -sk -o /dev/null -w 'no-auth=%{http_code}\n' https://<公网IP>/
curl -sk -u 'mw:<口令>' -o /dev/null -w 'auth=%{http_code}\n' https://<公网IP>/
```

期望：health `200`；local/session `200`；公网 no-auth `401`；auth `200`。

## 7. 明确边界

- 身份是**合成身份**，不是生产 OIDC。Basic Auth 是外挂的一道门，不是 Gate D。
- 自签证书没有 CA 信任链，首次连接告警被点掉后无法验证服务器身份。
- 合成 worker 只消费 `local.simulate`，**不消费 outbox**。fanout 分支会停在 `QUEUED`，需另跑 `scripts/mw_outbox_dispatcher.py` 并提供 worker JWT（见 `docs/V3.0.1-CHANGES-AND-KNOWN-ISSUES.md`）。
- PG / 真实探针 / 生产 Worker / TLS 生产身份仍未运行，沿用 Gate B–E 的既有约束。
