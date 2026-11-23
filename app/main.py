"""CLI: python -m app.main <lệnh>

serve                         chạy API (uvicorn)
worker --queues docling,ai    worker chạy liên tục (compose / VM)
job --queues ai --idle 30     xử lý đến khi hàng đợi rỗng rồi thoát (Container Apps Job / ECS task)
create-admin EMAIL            tạo tài khoản admin (hỏi mật khẩu)
upload FILE [--kind akahon] [--book-page 536] [--from 1 --to 10]
status DOC_ID                 xem trạng thái tài liệu + trang
"""

from __future__ import annotations

import argparse
import getpass
import logging
import signal
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="app.main")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    for name in ("worker", "job"):
        w = sub.add_parser(name)
        w.add_argument("--queues", default="docling,ai,light")
        w.add_argument("--idle", type=float, default=30, help="job: số giây không có việc thì thoát")
    a = sub.add_parser("create-admin")
    a.add_argument("email")
    u = sub.add_parser("upload")
    u.add_argument("file")
    u.add_argument("--name", default="")
    u.add_argument("--kind", default="other")
    u.add_argument("--book-page", type=int, default=1)
    u.add_argument("--from", dest="page_from", type=int)
    u.add_argument("--to", dest="page_to", type=int)
    st = sub.add_parser("status")
    st.add_argument("doc_id")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("app.api.server:app", host=args.host, port=args.port, reload=args.reload)
        return 0

    import app.steps.handlers  # noqa: F401
    from app.services.container import get_container

    c = get_container()
    if args.cmd in ("worker", "job"):
        from app.services.jobs import QUEUES, run_worker

        queues = [q.strip() for q in args.queues.split(",") if q.strip()]
        bad = set(queues) - set(QUEUES)
        if bad:
            ap.error(f"queue không hợp lệ: {bad}")
        stopping = {"v": False}

        def _stop(*_):
            stopping["v"] = True

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
        n = run_worker(c, queues, drain=args.cmd == "job", idle_exit_s=args.idle, stop=lambda: stopping["v"])
        logging.info("worker dừng, đã xử lý %d message", n)
        return 0
    if args.cmd == "create-admin":
        from app.core.util import hash_password, new_id, now_iso
        from app.domain.models import Role, User

        pw = getpass.getpass("Mật khẩu (≥10 ký tự): ")
        if len(pw) < 10:
            print("Mật khẩu quá ngắn", file=sys.stderr)
            return 1
        existing = c.repo.find_user_by_email(args.email)
        u = existing or User(id=new_id(), email=args.email, created_at=now_iso())
        u.role, u.password_hash, u.active = Role.admin, hash_password(pw), True
        c.repo.save_user(u)
        print(f"Admin: {u.email}")
        return 0
    if args.cmd == "upload":
        from pathlib import Path

        from app.services.pipeline import create_document

        p = Path(args.file)
        doc = create_document(
            c,
            data=p.read_bytes(),
            filename=p.name,
            name=args.name,
            kind=args.kind,
            book_page_start=args.book_page,
            page_from=args.page_from,
            page_to=args.page_to,
            actor="cli",
        )
        print(doc.id)
        return 0
    if args.cmd == "status":
        doc = c.repo.get_doc(args.doc_id)
        if not doc:
            print("Không tìm thấy", file=sys.stderr)
            return 1
        print(f"{doc.name}  status={doc.status.value}  stats={doc.stats}")
        for pg in c.repo.list_pages(doc.id):
            print(
                f"  p{pg.page:>4} (sách {pg.book_page}) {pg.status.value:<9} {pg.route or '-':<5} "
                f"low={pg.scores.low_grade:<11} {','.join(pg.route_reasons)}"
            )
        from app.services import inspect as insp

        r = insp.recognition_summary(c, doc.id, build=False)
        n = r["elements"]

        def pct(k: int) -> str:
            return f"{100 * k / n:5.1f}%" if n else "    —"

        cur, ini = r["current"], r["initial"]
        failed, pending = r["pages_failed"] or "-", r["pages_pending"] or "-"
        print(f"認識結果 (phần tử nội dung: {n}; trang lỗi: {failed}; chưa xong: {pending})")
        print(
            f"  hiện tại   良好 {pct(cur['good'] + cur['fixed'])} (trong đó 修正・確認 {pct(cur['fixed'])})"
            f"  要確認 {pct(cur['weak'])}  未認識 {pct(cur['unread'])}"
        )
        print(
            f"  máy đọc    良好 {pct(ini['good'])}  要確認 {pct(ini['weak'])}  未認識 {pct(ini['unread'])}"
            + (f"  (ước tính {r['estimated']} phần tử)" if r["estimated"] else "")
        )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
