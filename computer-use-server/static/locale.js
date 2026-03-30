// =============================================================================
// Locale module — i18n for file-server preview SPA
// =============================================================================
//
// Usage in browser:
//   import { t } from '/static/locale.js';
//   t('files')          → 'Files'
//   t('showing_rows', { n: 5000 }) → 'Showing 1000 of 5000 rows'
//
// Usage in Node.js tests:
//   import { TRANSLATIONS, createT } from './locale.js';
//   const t = createT('en');

export const TRANSLATIONS = {
  ru: {
    // Tabs
    files: 'Файлы',
    browser: 'Браузер',
    subagent: 'Субагент',

    // File selector
    no_file_selected: 'Файл не выбран',
    copied: 'Скопировано',

    // Toolbar
    open_new_tab: 'Открыть в новой вкладке',
    waiting_files: 'Ожидание файлов...',
    download_file: 'Скачать файл',
    download_all: 'Скачать все (zip)',

    // Sync status
    checking: 'Проверка...',
    synced: 'Синхронизировано',
    error: 'Ошибка',

    // Renderers
    pptx_fail: 'Не удалось открыть PPTX',
    drawio_fail: 'Не удалось открыть Draw.io',
    showing_rows: 'Показано 1000 из {n} строк',

    // Dashboard
    beta: 'Бета',
    hero_desc: 'Автономный ИИ-агент в изолированном контейнере. Может самостоятельно писать и запускать код, создавать файлы, анализировать данные.',
    pd_warning: '⚠️ Не загружайте файлы с персональными данными клиентов',
    skip_perms: 'Пропустить запросы разрешений',
    dangerous_warn: '⚠ Claude будет выполнять любые операции без подтверждения — файлы, команды, сеть. Включай только для доверенных задач.',
    open_terminal: 'Открыть терминал',
    upload_file: 'Загрузить файл',
    how_to_use: 'Как пользоваться',
    running_now: 'Сейчас работает',
    claude_running: 'Claude Code работает',
    less_than_min: 'менее минуты',
    min_suffix: ' мин',
    stop: 'Остановить',

    // Terminal
    starting_terminal: 'Запуск терминала...',
    terminal_fail: 'Не удалось запустить терминал (контейнер не найден)',
    server_fail: 'Не удалось подключиться к серверу',
    restore_fail: 'Не удалось восстановить контейнер',
    container_stopped: 'Контейнер остановлен',
    container_removed: 'Контейнер удалён',
    container_stopped_desc: 'Контейнер завершил работу. Данные сохранены — можно перезапустить.',
    container_removed_desc: 'Контейнер был удалён, но данные сохранены. Можно восстановить.',
    container_generic_desc: 'Убедитесь что контейнер запущен и попробуйте снова.',
    restoring: 'Восстановление...',
    starting: 'Запуск...',
    restore_container: 'Восстановить контейнер',
    restart_container: 'Перезапустить контейнер',
    back: 'Назад',
    session_ended: '[Сессия завершена]',
    select_mode_title: 'Режим выделения текста (отключает мышь в терминале)',
    select_on: '✂ Выделение',
    select_off: '✂ Выделить',
    terminate: 'Завершить',

    // File renderers — loading & errors
    loading_pdf: 'Загрузка PDF...',
    showing_pages: 'Показано {max} из {total} страниц.',
    load_fail: 'Не удалось загрузить файл',
    loading: 'Загрузка...',
    download: 'Скачать',
    audio_unsupported: 'Ваш браузер не поддерживает аудио.',
    video_unsupported: 'Ваш браузер не поддерживает видео.',

    // Empty states
    no_files_yet: 'Файлов пока нет',
    no_files_desc: 'ИИ-агент ещё не передал вам файлы.<br/>Попросите его создать документ, презентацию или таблицу — результат появится здесь.',
    no_files_example: '«Сделай презентацию о нашей компании на 5 слайдов»',
    browser_title: 'Совместный AI-браузер',
    browser_desc: 'ИИ-агент может открывать разрешённые службой ИБ сайты, извлекать из них нужную информацию и навигировать по страницам.<br/>Список доступных сайтов можно расширить по согласованию.',
    browser_example: 'Попросите ИИ Агента в чате, например:<br/><br/>«Открой example.com в браузере и найди мне BMW б/у до 5\u00a0млн\u00a0рублей»',
    loading_browser: 'Загрузка браузера...',
    browser_connect_fail: 'Не удалось подключиться к браузеру',

    // Dashboard tables
    uploaded_files: 'Загруженные файлы',
    th_file: 'Файл',
    th_size: 'Размер',
    copy_path: 'Копировать путь',
    prev_sessions: 'Предыдущие сессии',
    th_task: 'Задача',
    th_date: 'Дата',
    resume: 'Продолжить',
    dash_hint: 'Откройте терминал или делегируйте задачу в чате, например: «создай презентацию о компании»',

    // Auth (browser-viewer)
    auth_required: 'Требуется авторизация',
    username: 'Имя пользователя',
    password: 'Пароль',
    cancel: 'Отмена',
    login: 'Войти',
  },

  en: {
    // Tabs
    files: 'Files',
    browser: 'Browser',
    subagent: 'Sub-agent',

    // File selector
    no_file_selected: 'No file selected',
    copied: 'Copied',

    // Toolbar
    open_new_tab: 'Open in new tab',
    waiting_files: 'Waiting for files...',
    download_file: 'Download file',
    download_all: 'Download all (zip)',

    // Sync status
    checking: 'Checking...',
    synced: 'Synced',
    error: 'Error',

    // Renderers
    pptx_fail: 'Failed to open PPTX',
    drawio_fail: 'Failed to open Draw.io',
    showing_rows: 'Showing 1000 of {n} rows',

    // Dashboard
    beta: 'Beta',
    hero_desc: 'Autonomous AI agent in an isolated container. Can write and run code, create files, analyze data.',
    pd_warning: '⚠️ Do not upload sensitive or confidential files',
    skip_perms: 'Skip permission prompts',
    dangerous_warn: '⚠ Claude will perform any operations without confirmation — files, commands, network. Enable only for trusted tasks.',
    open_terminal: 'Open terminal',
    upload_file: 'Upload file',
    how_to_use: 'How to use',
    running_now: 'Currently running',
    claude_running: 'Claude Code running',
    less_than_min: 'less than a minute',
    min_suffix: ' min',
    stop: 'Stop',

    // Terminal
    starting_terminal: 'Starting terminal...',
    terminal_fail: 'Failed to start terminal (container not found)',
    server_fail: 'Failed to connect to server',
    restore_fail: 'Failed to restore container',
    container_stopped: 'Container stopped',
    container_removed: 'Container removed',
    container_stopped_desc: 'Container finished. Data saved — you can restart.',
    container_removed_desc: 'Container was removed, but data is saved. You can restore it.',
    container_generic_desc: 'Make sure the container is running and try again.',
    restoring: 'Restoring...',
    starting: 'Starting...',
    restore_container: 'Restore container',
    restart_container: 'Restart container',
    back: 'Back',
    session_ended: '[Session ended]',
    select_mode_title: 'Text selection mode (disables mouse in terminal)',
    select_on: '✂ Selection',
    select_off: '✂ Select',
    terminate: 'Terminate',

    // File renderers — loading & errors
    loading_pdf: 'Loading PDF...',
    showing_pages: 'Showing {max} of {total} pages.',
    load_fail: 'Failed to load file',
    loading: 'Loading...',
    download: 'Download',
    audio_unsupported: 'Your browser does not support audio.',
    video_unsupported: 'Your browser does not support video.',

    // Empty states
    no_files_yet: 'No files yet',
    no_files_desc: 'The AI agent has not created any files yet.<br/>Ask it to create a document, presentation, or spreadsheet — the result will appear here.',
    no_files_example: '"Create a 5-slide presentation about our company"',
    browser_title: 'Shared AI Browser',
    browser_desc: 'The AI agent can open approved websites, extract information, and navigate pages.<br/>The list of available sites can be expanded upon request.',
    browser_example: 'Ask the AI Agent in the chat, for example:<br/><br/>"Open example.com in the browser and take a screenshot"',
    loading_browser: 'Loading browser...',
    browser_connect_fail: 'Failed to connect to browser',

    // Dashboard tables
    uploaded_files: 'Uploaded files',
    th_file: 'File',
    th_size: 'Size',
    copy_path: 'Copy path',
    prev_sessions: 'Previous sessions',
    th_task: 'Task',
    th_date: 'Date',
    resume: 'Resume',
    dash_hint: 'Open the terminal or delegate a task in chat, e.g. "create a presentation about the company"',

    // Auth (browser-viewer)
    auth_required: 'Authorization required',
    username: 'Username',
    password: 'Password',
    cancel: 'Cancel',
    login: 'Login',
  },
};

/**
 * Create a translation function for a specific language.
 * @param {string} lang - Language code ('ru', 'en', etc.)
 * @returns {function(string, object?): string}
 */
export function createT(lang) {
  const dict = TRANSLATIONS[lang] || TRANSLATIONS.en;
  return function t(key, params) {
    let msg = dict[key] || TRANSLATIONS.en[key] || key;
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        msg = msg.replace(`{${k}}`, String(v));
      }
    }
    return msg;
  };
}

// Browser auto-detection: defaults to English
const _detectLang = () => {
  return 'en';
};

export const LANG = _detectLang();
export const t = createT(LANG);
