import { useTranslation } from "react-i18next";
import type { Doc } from "@/lib/types";

export function docPageTotal(doc: Doc) {
  return doc.page_to - doc.page_from + 1;
}

/** Chú thích dưới thanh tiến độ, theo bước hiện tại (trang ở giai đoạn OCR, chunk ở giai đoạn chunk). */
export function useDocProgressLabel() {
  const { t } = useTranslation();
  return (doc: Doc) => {
    const s = doc.stats;
    if (["chunk_review", "indexing"].includes(doc.status))
      return t("documents.chunksApproved", { n: s.chunks_approved ?? 0, total: s.chunks ?? 0 });
    if (doc.status === "indexed") return t("documents.chunksIndexed", { n: s.chunks_indexed ?? s.chunks ?? 0 });
    return t("documents.pagesApproved", { n: s.approved ?? 0, total: docPageTotal(doc) });
  };
}
