import { createInstance } from 'i18next'
import { initReactI18next } from 'react-i18next'
import { resources } from './resources.js'
import { readLanguage, saveLanguage } from './preference.js'

const i18n = createInstance()
i18n.use(initReactI18next).init({
  resources,
  lng: readLanguage(),
  fallbackLng: 'zh-CN',
  supportedLngs: ['zh-CN', 'en-US'],
  load: 'currentOnly',
  keySeparator: false,
  initAsync: false,
  interpolation: { escapeValue: false }, // React escapes rendered text.
  react: { useSuspense: false },
})

export function setLanguage(language) {
  return i18n.changeLanguage(saveLanguage(language))
}

export default i18n
