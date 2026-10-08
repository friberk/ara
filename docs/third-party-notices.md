# Third-party notices

Project code: GNU Affero General Public License version3; LICENSE contains the license text. This choice was approved by the user. Dependency notices are preserved; this file does not change their licenses.

- MinIO community: AGPL-3.0, pinned source commit7aac2a2c5b7c882e68c1ce017d8256be2feea27f. Source: https://github.com/minio/minio/tree/7aac2a2c5b7c882e68c1ce017d8256be2feea27f. The source image build is reproducible from docker/minio.Dockerfile. Upstream is archived/unmaintained; no public storage service is exposed by default.
- PyMuPDF/MuPDF: AGPL/commercial terms. Source and licensing: https://pymupdf.readthedocs.io/en/latest/about.html and https://github.com/pymupdf/PyMuPDF. The skill and backend resolve their documented versions independently through lockfiles.
- React, Vite, Tailwind, shadcn/ui and other frontend packages retain upstream notices in their distributed packages/source. shadcn-style component code is adapted for the project; dependencies are listed in package-lock.json.
- Python/backend dependencies retain their upstream licenses; exact versions/hashes are recorded in uv.lock. Dramatiq is LGPL-3.0; its application integration does not modify the upstream library.
- Assignment materials and pre-existing writing skills remain user reference files. Project licensing does not assert ownership of those materials or uploaded research papers.

Full upstream dependency licensing metadata is available in installed distributions. Do not redistribute third-party model weights or research PDFs without checking their particular licenses.
