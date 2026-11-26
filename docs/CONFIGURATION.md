# Configuration

Nothing is hard-coded. Each setting is taken from the first place that gives it:

| Setting | Command-line flag | Environment variable | Config file key | Default |
|---|---|---|---|---|
| small files: prepared segments, versions, journals, exports, uploads | `--data-dir` | `SURFACE_ENHANCER_DATA` | `data_dir` | `~/.surface-enhancer/data` |
| big files: straightened blocks, downloaded scan blocks | `--cache-dir` | `SURFACE_ENHANCER_CACHE` | `cache_dir` | `~/.surface-enhancer/cache` |
| address to listen on | `--host` | `SURFACE_ENHANCER_HOST` | `host` | `127.0.0.1` |
| port | `--port` | `SURFACE_ENHANCER_PORT` | `port` | `8800` |
| compute threads of the preload | `--threads` | `SURFACE_ENHANCER_THREADS` | `threads` | `4` |
| custom CA bundle for HTTPS / S3 | | `SSL_CERT_FILE`, `AWS_CA_BUNDLE` | `ca_bundle` | system |
| largest upload, in MB | | | `max_upload_mb` | `2048` |

The config file is JSON. It is looked for at `--config`, then `SURFACE_ENHANCER_CONFIG`, then
`./surface-enhancer.json`, then `~/.surface-enhancer/config.json`:

```json
{
  "data_dir": "/data/surface-enhancer",
  "cache_dir": "/fast-disk/surface-enhancer-cache",
  "port": 8800,
  "threads": 8
}
```

Put the cache on a fast disk with room: about 81 bytes per pixel of the flat page for each prepared segment, plus
2 MB per downloaded scan block. The cache can be deleted at any time; it is rebuilt by preparing the segment again
(your versions and journal are in the data folder and are not affected).

## Network

- Volumes are read anonymously and read-only (`https://`, `s3://`). Nothing is ever uploaded.
- Behind a proxy or an antivirus that inspects TLS, downloads fail with a certificate error: export the root
  certificate it uses to a `.pem` file and give it as `ca_bundle` (or set `SSL_CERT_FILE` and `AWS_CA_BUNDLE`).
- `prepare --offline` never downloads: blocks missing from the cache are left black and counted.
- `prepare --chunk-cache DIR` reuses a folder of 128³ blocks named `<kz>_<ky>_<kx>.npy` you already have.

## Security

The server is meant for one person on one machine. It has **no authentication**, and through it the page can read
tifxyz folders and write new folders anywhere your account can. It therefore listens on `127.0.0.1` only, refuses
requests whose `Host` is not local or whose `Origin` is another site, and only accepts JSON bodies sent as
`application/json`. If you pass `--host 0.0.0.0` you remove that protection: do it only on a network you trust.

A port already used by another program is refused at start (checked on every address, not only `127.0.0.1`).
