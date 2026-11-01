# Traduzioni

Lingue: **italiano** e **inglese**. Si sceglie dal selettore **IT / EN** in fondo alla pagina (o
Impostazioni, chiave `ui.language`); vale per tutti gli utenti della dashboard.

## Come funziona

- La chiave di ogni traduzione è il **testo italiano**: se una traduzione manca compare l'italiano, mai un errore.
- Catalogo inglese: `astreo_monitor/i18n/en.json` (`"testo italiano": "English text"`).
- Pagine: `{{ _("testo") }}`; script: `t("testo")`, con segnaposto `t("Disco {p0}", { p0: nome })`.
- La stessa lingua vale per **notifiche** (email, Telegram, WhatsApp, avvisi posticipati, messaggi di
  prova), **riepilogo settimanale** e **risposte del bot**. Il bot accetta i comandi in entrambe le lingue
  (`/stato` o `/status`, `/servizi` o `/services`, `/controlli` o `/checks`, `/connessione` o
  `/connection`, `/aiuto` o `/help`); il menu di Telegram mostra quelli della lingua scelta.
- I testi composti dai job e salvati (stato della connessione, motivi SMART, nomi delle scadenze, eventi)
  restano in italiano nel database e vengono tradotti quando si leggono: i modelli sono in
  `i18n.STORED_TEMPLATES`.
- Gli avvisi già inviati restano nel registro nella lingua in cui sono partiti.
- **Comandi da terminale** (installatore, `update.sh`, `install.sh`, verifiche, diagnosi, migrazione):
  lingua da `ASTREO_LANG`, poi `language` in `install.ini`, poi `LANG` del sistema. L'installatore chiede
  la lingua come prima domanda e la imposta anche per dashboard e notifiche.
- README in inglese (`README.md`) e italiano (`README.it.md`); guida di installazione anche in inglese
  (`docs/en/installation.md`). Il resto della documentazione è in italiano.
- I log tecnici (journal) restano in italiano.

## Aggiungere o modificare un testo

1. Nella pagina o nello script usa `{{ _("…") }}` / `t("…")`.
2. Aggiungi la voce in `en.json`, con gli stessi segnaposto.
3. `bash scripts/verifica.sh`: il test `test_catalogo_inglese_completo` segnala i testi senza traduzione.

Strumenti di sviluppo: `scripts/i18n_wrap_templates.py` e `scripts/i18n_wrap_js.py` avvolgono
automaticamente i testi italiani nuovi.
