"""Settings: where the data lives, where the big cache lives, which port to listen on.

Nothing is hard-coded. Each value is resolved in this order (first hit wins):

1. command-line flag (``--data-dir``, ``--cache-dir``, ``--host``, ``--port``, ``--config``);
2. environment variable (``SURFACE_ENHANCER_DATA``, ``SURFACE_ENHANCER_CACHE``, ``SURFACE_ENHANCER_HOST``,
   ``SURFACE_ENHANCER_PORT``, ``SURFACE_ENHANCER_CONFIG``);
3. config file (JSON): the one given with ``--config``, else ``surface-enhancer.json`` in the current directory,
   else ``~/.surface-enhancer/config.json``;
4. default: ``~/.surface-enhancer/data`` and ``~/.surface-enhancer/cache``, ``127.0.0.1``, port ``8800``.

Config file keys: ``data_dir``, ``cache_dir``, ``host``, ``port``, ``ca_bundle``, ``threads``, ``max_upload_mb``.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_PORT = 8800
HOME = Path.home() / ".surface-enhancer"
CONFIG_NAME = "surface-enhancer.json"


@dataclass
class Settings:
    data_dir: Path
    cache_dir: Path
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    ca_bundle: str | None = None      # custom CA bundle for HTTPS / S3 (corporate proxy, antivirus TLS inspection)
    threads: int = 4                  # worker threads for the preload (the machine stays usable)
    max_upload_mb: int = 2048
    config_file: str | None = None

    # ---- derived folders ----
    @property
    def segments_dir(self) -> Path:
        return self.data_dir / "segments"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def state_file(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def segment_cache_dir(self) -> Path:
        return self.cache_dir / "segments"

    @property
    def volume_cache_dir(self) -> Path:
        return self.cache_dir / "volumes"

    def ensure(self) -> "Settings":
        for d in (self.segments_dir, self.uploads_dir, self.jobs_dir, self.segment_cache_dir, self.volume_cache_dir):
            d.mkdir(parents=True, exist_ok=True)
        return self

    def public(self) -> dict:
        d = asdict(self)
        d["data_dir"] = str(self.data_dir)
        d["cache_dir"] = str(self.cache_dir)
        return d

    def apply_environment(self) -> None:
        """Make the optional CA bundle visible to the HTTP / S3 libraries (never overrides what the user already set)."""
        if self.ca_bundle:
            for k in ("SSL_CERT_FILE", "AWS_CA_BUNDLE", "REQUESTS_CA_BUNDLE"):
                os.environ.setdefault(k, self.ca_bundle)


def sample_dir() -> Path:
    """Where the bundled sample is: next to the package (a clone used as it is), else in the current folder (the tool
    installed with pip and run from the clone), else where SURFACE_ENHANCER_SAMPLE says. The folder may not exist."""
    here = Path(__file__).resolve().parents[1] / "sample"
    for d in (os.environ.get("SURFACE_ENHANCER_SAMPLE"), here, Path.cwd() / "sample"):
        if d and (Path(d) / "segment" / "sample_scroll1" / "x.tif").is_file():
            return Path(d).resolve()
    return here


def _read_config(explicit: str | None) -> tuple[dict, str | None]:
    candidates = [explicit or os.environ.get("SURFACE_ENHANCER_CONFIG"), Path.cwd() / CONFIG_NAME, HOME / "config.json"]
    for c in candidates:
        if not c:
            continue
        p = Path(c).expanduser()
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8")), str(p)
            except (OSError, ValueError) as e:
                raise SystemExit(f"cannot read the config file {p}: {e}")
        if c is candidates[0]:
            raise SystemExit(f"config file not found: {p}")
    return {}, None


def load_settings(data_dir=None, cache_dir=None, host=None, port=None, config=None, threads=None) -> Settings:
    cfg, used = _read_config(config)
    env = os.environ

    def pick(cli, env_key, cfg_key, default):
        if cli not in (None, ""):
            return cli
        if env.get(env_key):
            return env[env_key]
        if cfg.get(cfg_key) not in (None, ""):
            return cfg[cfg_key]
        return default

    s = Settings(
        data_dir=Path(pick(data_dir, "SURFACE_ENHANCER_DATA", "data_dir", HOME / "data")).expanduser().resolve(),
        cache_dir=Path(pick(cache_dir, "SURFACE_ENHANCER_CACHE", "cache_dir", HOME / "cache")).expanduser().resolve(),
        host=str(pick(host, "SURFACE_ENHANCER_HOST", "host", "127.0.0.1")),
        port=int(pick(port, "SURFACE_ENHANCER_PORT", "port", DEFAULT_PORT)),
        ca_bundle=cfg.get("ca_bundle") or None,
        threads=int(pick(threads, "SURFACE_ENHANCER_THREADS", "threads", 4)),
        max_upload_mb=int(cfg.get("max_upload_mb", 2048)),
        config_file=used,
    )
    s.apply_environment()
    return s


def add_settings_arguments(parser) -> None:
    g = parser.add_argument_group("where things live (see docs/CONFIGURATION.md)")
    g.add_argument("--data-dir", help="small files: prepared segments, versions, journals, exports (default: ~/.surface-enhancer/data)")
    g.add_argument("--cache-dir", help="big files: straightened scan blocks, downloaded scan chunks (default: ~/.surface-enhancer/cache)")
    g.add_argument("--config", help=f"JSON config file (default: ./{CONFIG_NAME}, then ~/.surface-enhancer/config.json)")


def settings_from_args(a) -> Settings:
    return load_settings(getattr(a, "data_dir", None), getattr(a, "cache_dir", None), getattr(a, "host", None), getattr(a, "port", None),
                         getattr(a, "config", None), getattr(a, "threads", None))
