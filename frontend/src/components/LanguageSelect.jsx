import { Select } from 'antd'
import { GlobalOutlined } from '@ant-design/icons'
import { useI18n } from '../i18n/useI18n'

const options = [
  { value: 'zh-CN', label: '简体中文' },
  { value: 'en-US', label: 'English' },
]

export default function LanguageSelect() {
  const { language, setLanguage, t } = useI18n()
  return (
    <Select
      className="language-select"
      aria-label={t('shell.language')}
      title={t('shell.language')}
      prefix={<GlobalOutlined aria-hidden="true" />}
      value={language}
      options={options}
      onChange={setLanguage}
    />
  )
}
