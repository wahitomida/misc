// ExhibiReport - Main Alpine.js App

function app() {
    return {
        darkMode: document.documentElement.classList.contains('dark'),
        showHelp: false,
        helpTab: 'start',

        init() {
            // ダークモード初期化（head のインラインスクリプトで既に html.dark は適用済み）
            const stored = localStorage.getItem('darkMode');
            if (stored !== null) {
                this.darkMode = stored === 'true';
            } else {
                this.darkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
            }
            this.applyDarkMode();

            // OS設定変更を監視
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
                if (localStorage.getItem('darkMode') === null) {
                    this.darkMode = e.matches;
                    this.applyDarkMode();
                }
            });
        },

        toggleDarkMode() {
            this.darkMode = !this.darkMode;
            localStorage.setItem('darkMode', this.darkMode);
            this.applyDarkMode();
        },

        applyDarkMode() {
            document.documentElement.classList.toggle('dark', this.darkMode);
        },
    };
}
