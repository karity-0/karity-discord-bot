# Karity Discord Bot

Self-hostable Discord bot for [Karity Obfuscator](https://github.com/karity-0/karity-obfuscator).
Version **0.1.0** provides one command:

```text
/obfuscate file:your_script.lua
```

The bot returns a protected `.lua` attachment using **Fast + Bare**, with build
duration and a private response. Server members do not need to install Karity.
The bot operator supplies their own Discord application, token, and always-on host.

## Supported input

- One non-empty UTF-8 `.lua` source file (UTF-8 BOM accepted).
- Lua **5.3**, standalone environment, **Fast** preset, **Bare** backend.
- Karity protection directives and literal macros are rejected in v0.1.0, because
  they can override the fixed preset/backend or exclude code from protection.
  Marker-like text inside strings and ordinary comments is allowed.
- No Lua 5.1, LuaJIT, Luau/Roblox, or cross-runtime compatibility is promised.
  Bare requires the engine's `runtime_specific` compatibility level. Validate the
  result in your intended host yourself; the bot never runs submitted or output Lua.

## Create and invite your Discord bot

1. Create an application at the [Discord Developer Portal](https://discord.com/developers/applications).
2. Open **Bot** and generate/reset its **Bot Token**. Put it in `DISCORD_TOKEN` in
   your local `.env` or hosting environment. Do not use a user token, application
   secret, or public key. Never commit or share the token.
3. In **Installation / OAuth2 URL Generator**, choose a server/guild installation
   with scopes **bot** and **applications.commands**. Invite the bot to your server.
   Grant **View Channels**, **Send Messages**, and **Attach Files** in the intended
   channel. Members need permission to **Use Application Commands**.
4. No privileged intents or Administrator permission are required. This bot uses
   slash-command attachments, not message-content scanning.
5. For initial testing, enable Discord Developer Mode, copy your server ID, and put
   it in `DISCORD_GUILD_ID`. Leave it blank for global registration across servers.
   Global commands may take time to appear. Changing registration scope can leave
   an older command visible; use a separate development application if needed.

The bot connects through Discord's gateway. No public HTTP endpoint or inbound
port forwarding is needed.
After startup, try `/obfuscate` with [examples/hello.lua](examples/hello.lua) or
[examples/functions.lua](examples/functions.lua).

## Quick start: Docker Compose

Install Git and Docker with Compose, then open a terminal in this repository.
Copy `.env.example` to `.env` and set `DISCORD_TOKEN` (and optionally your test server ID).

```sh
cp .env.example .env
docker compose up --build -d
docker compose logs -f bot
```

PowerShell: use `Copy-Item .env.example .env` for the copy step.

The image installs Python, the pinned headless dependencies, Lua/luac 5.3, and
the pinned engine commit. The `.env` is excluded from the image build. Compose
uses a non-root user, a read-only filesystem, temporary job storage, a 1 GiB
container memory cap, and no published ports.

Check generation without starting Discord:

```sh
docker compose run --rm --no-deps bot python -m karity_bot --smoke-test
```

Stop with `docker compose down`. Increase the container memory and tmpfs limits
in `compose.yaml` when increasing concurrency or job limits. Container image
tags and OS packages are not immutable; engine and Python runtime dependencies
are pinned, but the whole OS image is not a bit-for-bit reproducible build.

## Local setup: Windows or Linux

Requires **Python 3.12+**, **Git**, and network access to install dependencies.
Python 3.12–3.14 is recommended for native dependency wheels; newer versions
may require C/C++ build tools, particularly for Lupa.
On Linux, install Lua 5.3 and its compiler, for example:

```sh
sudo apt-get install git lua5.3
```

The pinned engine includes Windows `bin/lua.exe` and `bin/luac53.exe`.
The worker checks that both report Lua 5.3. macOS is not currently a validated
deployment target; Linux containers are the recommended portable deployment.

If Lupa falls back to a source build on Windows/Python 3.15 and fails while
building LuaJIT, install Visual C++ build tools and a Windows SDK, then install
Lupa without the unused LuaJIT modules before retrying `requirements.txt`:

```sh
python -m pip install lupa==2.8 --config-settings=--build-option=--no-luajit
python -m pip install -r requirements.txt
```

Use the venv's Python for these commands. The option is part of
[Lupa's build configuration](https://github.com/scoder/lupa/blob/lupa-2.8/setup.py).

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/setup_engine.py
Copy-Item .env.example .env
# Edit .env and set DISCORD_TOKEN and, for testing, DISCORD_GUILD_ID.
.\.venv\Scripts\python.exe -m karity_bot --smoke-test
.\.venv\Scripts\python.exe -m karity_bot
```

Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/setup_engine.py
cp .env.example .env
# Edit .env before starting Discord.
.venv/bin/python -m karity_bot --smoke-test
.venv/bin/python -m karity_bot
```

Run from the repository root. `.env` is loaded from the current directory;
existing environment variables take precedence. `--check-engine` checks the
engine pin, effective config, Lua tools, and worker limits without building.
`--smoke-test` also generates three built-in examples. Neither requires a token
or executes generated Lua.

`scripts/setup_engine.py` installs into a new `.engine` directory and refuses to
change an existing directory. A failed fetch leaves the partial directory for
inspection; select a new `--destination` before retrying. Set
`KARITY_ENGINE_PATH` to that destination if it is not `.engine`.

For an existing Karity checkout such as the sibling `lua-obfuscator`, skip the
download and set `KARITY_ENGINE_PATH=../lua-obfuscator` in `.env`. It must be on
the locked commit with no tracked edits. The bot does not alter that checkout.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `DISCORD_TOKEN` | required | Official Discord Bot Token |
| `DISCORD_GUILD_ID` | blank | Development server ID; blank registers globally |
| `KARITY_ENGINE_PATH` | `.engine` | Pinned, clean engine checkout |
| `KARITY_JOBS_PATH` | `.jobs` | Dedicated temporary directory for this bot instance |
| `MAX_INPUT_BYTES` | `262144` | 256 KiB upload limit, also checked while streaming |
| `MAX_OUTPUT_BYTES` | `8388608` | 8 MiB result limit; actual Discord limit can lower it |
| `JOB_TIMEOUT_SECONDS` | `120` | Worker wall time, including imports/tool checks |
| `JOB_MEMORY_MB` | `512` | Worker memory budget in MiB |
| `MAX_WORKSPACE_BYTES` | `134217728` | 128 MiB temporary storage budget per job |
| `MAX_CONCURRENCY` | `1` | Simultaneous download/build/delivery slots |
| `MAX_QUEUE_SIZE` | `4` | Additional waiting requests; `0` disables waiting |
| `QUEUE_TIMEOUT_SECONDS` | `120` | Maximum wait for a processing slot |
| `DOWNLOAD_TIMEOUT_SECONDS` | `30` | Attachment download deadline |

One queued/running request is allowed per Discord user, across all servers this
bot process serves. Admission occurs before download; results retain their slot
until delivery finishes. Upload delivery is limited to 45 seconds. The sum of
queue, download and job timeouts must be at most 780 seconds to leave room for
delivery within [Discord's interaction lifetime](https://github.com/discord/discord-api-docs/blob/main/developers/interactions/receiving-and-responding.mdx).
Queue state is in memory and is lost on restart. Use one bot process per token
and one dedicated jobs directory per instance.

## Engine integration and limits

The bot reuses Karity's CLI configuration resolver and pipeline builder in an
isolated Python subprocess; it does not copy the obfuscation implementation.
Its fixed selection is equivalent to:

```text
--profile builtin:fast --vm-option backend=bare --lua-version 5.3 --compatibility runtime_specific
```

It ignores the engine checkout's local/GUI config. Each worker checks the
resolved Fast preset against Karity's own preset catalog and explicitly verifies
Bare and Lua 5.3. Startup additionally verifies the checkout commit and tracked
cleanliness. The engine pin lives in `karity_bot/engine.lock.json`:

```text
Karity 1.6.0 / preset revision 6
65394dc8974a79ec4f2488d9dc1ee4800c21a323
```

- Windows: a Job Object limits aggregate worker/descendant committed memory and
  terminates descendants when the worker exits or is killed.
- Linux/POSIX: inherited `RLIMIT_AS` limits each process's virtual address space;
  CPU/file/core limits also apply. A separate process group is killed on timeout,
  cancellation, and completion. Compose adds an aggregate container memory cap.
- The parent monitors total workspace size roughly every 100 ms and checks it
  again after completion. POSIX also limits individual file sizes. Disk usage may
  briefly overshoot between checks; Compose's tmpfs adds a hard aggregate cap.
- Every job has a temporary working directory and its own `TMP`/`TEMP`/`TMPDIR`,
  including engine intermediates. Normal completion, failure, timeout and
  cancellation remove it. A host crash or force-kill of the entire bot can leave
  local `.jobs/job-*` directories; remove these only while the bot is stopped.
- Workers do not inherit the bot token or arbitrary environment secrets. All
  subprocess commands use argument arrays and never a shell.

These limits manage resource use; the worker is not a general-purpose security
sandbox. The supplied container has outbound network access for Discord.

## Privacy

Command responses and result attachments are ephemeral. Files still pass through
Discord, and the bot operator's machine receives the input. Ephemeral delivery is
not end-to-end encryption or a guarantee that Discord deletes its copies.

The bot does not store source history or log source text, original filenames,
signed attachment URLs, tokens, engine diagnostics, server paths or tracebacks.
Logs contain fixed status codes, timings and output byte counts. Engine stdout
and stderr are discarded because diagnostics can contain source excerpts.

## Development and tests

Install `requirements.txt`; tests use Python's built-in `unittest`.

```sh
python -m unittest discover -s tests -v
python -m karity_bot --smoke-test
```

Use your venv's Python as in the setup instructions. Integration tests discover
the sibling `lua-obfuscator` or `.engine`, or use `KARITY_TEST_ENGINE_PATH`.
They skip with an explicit reason if no engine checkout is available. Tests cover
private command responses, attachment validation/stream limits, safe error
messages, queue fairness/capacity/cancellation, real worker memory/time/storage
limits, descendant termination, cleanup, and real Fast + Bare generation.

Lua samples include `print(1)`, tables/loops, functions/strings, invalid syntax,
and a file-writing script whose side effect must never occur. Neither uploaded
source nor protected output is executed. Builds can invoke Karity's trusted Lua
compiler/helper tools to compile or dump generated functions.

To install the optional `karity-bot` console entry point for development:

```sh
python -m pip install -e .
```

When upgrading the engine, review its interfaces and preset definitions, update
the lock deliberately, and rerun integration tests and platform limits tests.
Do not silently track the engine's default branch. End-to-end Discord testing
requires your own bot token and test server; Docker deployment needs a working
Docker runtime. Public-bot rollout additionally requires operator capacity
testing and the Discord application's appropriate installation/distribution settings.

## License

MIT. Karity remains a separate dependency under its own MIT license. Use the
service for source you own or have permission to protect.
