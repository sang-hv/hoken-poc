import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./en";
import ja from "./ja";

export const LANGS = [
  { code: "ja", label: "日本語" },
  { code: "en", label: "English" },
] as const;

function initial(): string {
  try {
    const saved = localStorage.getItem("hoken.lang");
    if (saved === "en" || saved === "ja") return saved;
  } catch {
    /* localStorage có thể bị chặn */
  }
  return "ja"; // UI v2: demo cho khách Nhật — mặc định tiếng Nhật, đổi được ở thanh trên
}

i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, ja: { translation: ja } },
  lng: initial(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  returnNull: false,
});

i18n.on("languageChanged", (lng) => {
  document.documentElement.lang = lng;
  try {
    localStorage.setItem("hoken.lang", lng);
  } catch {
    /* bỏ qua */
  }
});
document.documentElement.lang = i18n.language;

export default i18n;
