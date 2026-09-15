import { useTranslation } from 'react-i18next'
import i18n, { setLanguage } from './index.js'

export function useI18n() {
  const { t } = useTranslation(undefined, { i18n })
  return { t, language: i18n.resolvedLanguage || 'zh-CN', setLanguage }
}
