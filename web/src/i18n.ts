import { createInstance } from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import ru from "./locales/ru.json";
import { DEFAULT_LOCALE, readLocale, SUPPORTED_LOCALES } from "./lib/localePreferences";

const i18n = createInstance();

void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    ru: { translation: ru },
  },
  lng: readLocale(),
  fallbackLng: DEFAULT_LOCALE,
  supportedLngs: [...SUPPORTED_LOCALES],
  load: "languageOnly",
  initAsync: false,
  interpolation: { escapeValue: false },
});

export default i18n;
