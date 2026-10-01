# mega-facecompare-core

| Metadata | |
|---|---|
| Judul | README mega-facecompare-core (compreface-core) |
| Versi | 2.0.0 |
| Tanggal | 2026-10-01 |
| Owner | Tim Platform / DevOps |
| Status | Review |

| Versi | Tanggal | Penulis | Perubahan |
|---|---|---|---|
| 1.0.0 | 2026-09-29 | Claude Code | Versi awal (di monorepo `services/<service>/README.md`) |
| 2.0.0 | 2026-10-01 | Claude Code | Repo mandiri hasil split monorepo Mega-CompreFace |

**Layanan ML (deteksi & embedding wajah)** — image `mega/compreface-core`. Bagian dari CompreFace (fork Exadel CompreFace 1.2.0, Apache 2.0) yang dipecah
dari monorepo Mega-CompreFace menjadi 6 repo. Integrasi full-stack, monitoring, dokumentasi SDLC (SPEC,
ARCHITECTURE, RUNBOOK, SECURITY, TEST_PLAN) dan versi rilis bersama ada di
[mega-facecompare-deploy](https://scm.bankmegadev.com/cobs/data-management/application/mega-facecompare-deploy).

## Fungsi
Layanan ML (`embedding-calculator/`, Python 3.8, Flask + uWSGI): deteksi wajah, embedding 512 dimensi, plugin age/gender/mask/landmarks/pose. Stateless, tanpa akses DB, **tanpa koneksi keluar saat runtime** (model ter-bake di image).

Source aplikasi: `embedding-calculator/` (upstream Exadel; `Dockerfile`/`gpu.Dockerfile` upstream tetap disimpan sebagai referensi, tidak dipakai build). **Logika aplikasi upstream tidak diubah** di repo ini; perubahan hanya pada
build, konfigurasi, dan dokumentasi.

## Isi repo
| File | Isi |
|---|---|
| `Dockerfile` | Stage `base-cpu` (`python:3.8-slim-bullseye`, apt snapshot) / `base-gpu` (`nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu20.04`) → `builder` (lib native imagecodecs, pip, model dari `MODELS_IMAGE`, pytest) → `runtime` (tanpa toolchain, uid 33) |
| `docker/build-args.env` | Definisi varian (plugin/model, CPU/GPU, sumber model) — dibaca `scripts/build.sh --variant` |
| `docker/uwsgi.ini` | uWSGI tanpa setuid, port `$(ML_PORT)`, request log off |
| `.dockerignore` | Context: `embedding-calculator/{src,srcext,tools,sample_images,requirements.txt,pytest.ini}`, `docker/uwsgi.ini` |
| `scripts/build.sh` | Build `mega/compreface-core:<versi>` dari root repo (versi default: file `VERSION`); tulis `build/images.txt` |
| `scripts/push.sh` | Push ke registry (catat digest ke `build/digests.txt`) atau `--save <dir>` → tarball + `SHA256SUMS` untuk transfer air-gapped |
| `k8s/base/` | Manifest service ini saja (Deployment/StatefulSet, Service, ConfigMap, NetworkPolicy) |
| `k8s/overlays/{dev,prod}/` | Overlay per environment untuk service ini |
| `.gitlab-ci.yml` | validate → build → scan (Trivy) → push; registry & kredensial dari variabel CI |
| `.env.example` | Env var service ini (tanpa nilai rahasia) |

## Port & healthcheck
| Port | Healthcheck | Catatan |
|---|---|---|
| 3000 | `GET /healthcheck` → `{"status":"OK"}` | liveness/readiness; `GET /status` (varian, plugin); `POST /find_faces` |

## Env var
Non-rahasia (ConfigMap `compreface-core`, default juga di-bake di `Dockerfile`/`.env.example`):

| Variabel | Default | Catatan |
|---|---|---|
| `ML_PORT` | `3000` |  |
| `IMG_LENGTH_LIMIT` | `640` |  |
| `UWSGI_PROCESSES` | `2` | prod GPU: 4 |
| `UWSGI_THREADS` | `1` |  |
| `UWSGI_MAX_WORKER_LIFETIME` | `93600` |  |
| `LOGGING_LEVEL_NAME` | `info` |  |
| `TZ` | `Asia/Jakarta` |  |

Referensi lengkap seluruh service: `docs/CONFIGURATION.md` di repo deploy.

## Build
```bash
scripts/build.sh                       # → mega/compreface-core:$(cat VERSION)
scripts/build.sh --variant arcface-r100-gpu    # → mega/compreface-core:1.2.0-arcface-r100-gpu (PROD)
scripts/build.sh --variant default,arcface-r100-gpu
REGISTRY=registry.example.internal scripts/build.sh && scripts/push.sh
scripts/push.sh --save /media/transfer # air-gapped: docker save + SHA256SUMS → docker load di sisi internal
# manual (build context = root repo, tanpa akses ke repo lain):
docker build -t mega/compreface-core:1.2.0 .
```
Tag `latest` ditolak. Versi image dinaikkan dengan mengubah `VERSION` + `CHANGELOG.md`; versi yang dirilis
bersama dicatat di `versions.env` repo deploy.

## Run (lokal, tanpa orkestrasi)
```bash
cp .env.example .env    # isi nilai yang ditandai WAJIB
docker run -d --name compreface-core --read-only --tmpfs /tmp -p 3000:3000 mega/compreface-core:1.2.0
# GPU: docker run -d --gpus 1 ... mega/compreface-core:1.2.0-arcface-r100-gpu
curl -fsS http://127.0.0.1:3000/healthcheck
```
Untuk full-stack (5 service) gunakan `scripts/compose.sh` di repo deploy.

## Kubernetes
```bash
kubectl kustomize k8s/overlays/dev          # render
kubectl apply -k k8s/overlays/dev           # namespace compreface-dev harus sudah ada (dibuat repo deploy)
```
Namespace, NetworkPolicy default-deny + DNS egress, dan Secret dikelola di repo deploy. Repo deploy menyimpan
salinan `k8s/base/` repo ini di `k8s/services/compreface-core/` — setelah mengubah `k8s/base/`, jalankan
`scripts/sync-manifests.sh` di repo deploy.

## Kontrak ke service lain
Nama Service, port dan nama env var **tidak berubah** dibanding monorepo — perubahannya adalah breaking change
dan harus dikoordinasikan lewat repo deploy.

- **Dipanggil oleh**: `compreface-api` dan `compreface-admin` (`PYTHON_URL=http://compreface-core:3000`), `compreface-fe` (hanya `GET /core/status`).
- **Memanggil**: tidak ada (tanpa DB, tanpa egress).
- **Kompatibilitas embedding**: model calculator berbeda = embedding tidak kompatibel. PROD memakai varian `arcface-r100-gpu`; jangan override env plugin saat runtime dan jangan ganti varian di environment berisi data tanpa migrasi.

## Catatan operasional
Varian (`scripts/build.sh --variant <nama>`):

| Varian | Tag | Detector / Calculator | Pemakaian |
|---|---|---|---|
| `default` | `1.2.0` | `facenet.FaceDetector` / `facenet.Calculator` | dev (setara image resmi 1.2.0) |
| `arcface-r100-gpu` | `1.2.0-arcface-r100-gpu` | `insightface.FaceDetector@retinaface_r50_v1` / `insightface.Calculator@arcface-r100-msfdrop75` | **prod** |
| `arcface-r100`, `facenet`, `mobilenet`, `mobilenet-gpu` | `1.2.0-<varian>` | lihat `docker/build-args.env` | opsional |

Build membutuhkan akses ke `MODELS_IMAGE` (image resmi Exadel di-pin digest, atau mirror internal dengan digest yang sama), GitHub (lib native imagecodecs), PyPI dan snapshot.debian.org — lakukan di build host berinternet lalu bawa image dengan `scripts/push.sh --save`. Runtime sepenuhnya offline. Terukur: Ready + inferensi pertama 48 s (CPU) / 25 s (GPU); ≈ 2,56 GB VRAM per proses uWSGI.

## Lisensi
Apache License 2.0 — lihat [LICENSE](LICENSE) dan [NOTICE](NOTICE) (atribusi Exadel, Inc. dipertahankan).
