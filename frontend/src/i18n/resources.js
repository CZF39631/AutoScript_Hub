import shell from './locales/shell.js'
import execution from './locales/execution.js'
import workspace from './locales/workspace.js'
import management from './locales/management.js'

export const dictionaries = { shell, execution, workspace, management }

export const resources = {
  'zh-CN': { translation: Object.assign({}, ...Object.values(dictionaries).map(value => value.zh)) },
  'en-US': { translation: Object.assign({}, ...Object.values(dictionaries).map(value => value.en)) },
}
