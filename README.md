# Google Data Portability API → AWS Lambda

Questo repository contiene una **AWS Lambda** (Python) che usa la [Data Portability API](https://developers.google.com/data-portability/user-guide/overview) di Google per esportare dati collegati a **liste salvate** e **luoghi preferiti** in Google Maps tramite i resource group ufficiali:

| Resource group (API) | Scope OAuth |
| --- | --- |
| `saved.collections` | `https://www.googleapis.com/auth/dataportability.saved.collections` |
| `maps.starred_places` | `https://www.googleapis.com/auth/dataportability.maps.starred_places` |

L’API lavora **per archivio**: si avvia un job (`portabilityArchive:initiate`), si attende lo stato `COMPLETE`, poi si scaricano gli URL firmati (tipicamente CSV/ZIP). Non esiste un endpoint REST per “una sola lista per ID”; per isolare una o più liste si filtrano le righe esportate (es. per `title`, `tags`, `collection_description` nel CSV di `saved.collections`), come da [schema Saved](https://developers.google.com/data-portability/schema-reference/save).

---

## Prerequisiti Google Cloud

1. **Disponibilità** della Data Portability API per la tua area e tipologia di account ([linee guida Google](https://developers.google.com/data-portability/user-guide/overview)).
2. **Progetto Google Cloud** con [fatturazione abilitata](https://developers.google.com/data-portability/user-guide/setup) e API **Data Portability API** attiva.
3. **Schermata di consenso OAuth** e **client OAuth** (tipo “Desktop” o “Web” a seconda di come ottieni il refresh token), con gli scope elencati sopra. Seguire [Configure OAuth](https://developers.google.com/data-portability/user-guide/configure-oauth) e [Scopes](https://developers.google.com/data-portability/user-guide/scopes).
4. Un **refresh token** OAuth con quegli scope (vedi sotto). Ricorda: Google richiede **verifica app** per uso pubblico; in fase di sviluppo puoi usare utenti di test.

**Nota:** la documentazione indica di avviare l’export entro **24 ore** dal consenso utente (`portabilityArchive.initiate`).

---

## Autenticazione (credenziali nella Lambda)

Le credenziali OAuth stanno in un file **`secret.json`** in root del repo (vedi `secret.json.example`). Terraform legge quel file e imposta la variabile d’ambiente **`GOOGLE_OAUTH_JSON`** sulla Lambda.

Formato minimo:

```json
{
  "client_id": "xxx.apps.googleusercontent.com",
  "client_secret": "xxx",
  "refresh_token": "xxx"
}
```

È supportato anche il JSON client Google con chiavi `installed` / `web` (come in `_normalize_oauth_secret` nel codice).

### Configurazione Terraform

1. Copia `terraform/terraform.tfvars.example` in `terraform/terraform.tfvars` (il file `terraform.tfvars` è in `.gitignore`).
2. Imposta `google_oauth_json_file` se il tuo `secret.json` non è in `../secret.json` rispetto alla cartella `terraform/`.

Esempio:

```hcl
google_oauth_json_file = "../secret.json"
```

`terraform apply` inietta il contenuto del file nelle env della Lambda. **Attenzione:** il JSON finisce anche nello **state Terraform** locale; non committare `terraform.tfstate` né `secret.json`.

### Cos’è il refresh token e ogni quanto va aggiornato

- **Access token:** breve durata (ordine di un’ora). La Lambda lo ottiene automaticamente con `grant_type=refresh_token` quando serve.
- **Refresh token:** lunga durata; serve a Google per emettere nuovi access token **senza** rifare il login nel browser. Non ha una scadenza fissa “da rinnovare ogni X giorni” nel flusso normale.
- Va **rigenerato** (nuovo consenso OAuth) se: l’utente revoca l’app, cambi client OAuth, Google invalida il token per inattività molto prolungata o politiche di sicurezza, o modifichi gli scope richiesti.

### Script locale (consigliato)

Dal repository:

```bash
python scripts/get_refresh_token.py
```

1. Nel client OAuth (Desktop o Web), aggiungi tra gli **URI di reindirizzamento autorizzati**: `http://127.0.0.1:8090/` (identico allo script).
2. In `secret.json` devono esserci almeno `client_id` e `client_secret` (come nel download Google o in chiaro).
3. Lo script apre il browser, dopo il consenso **scrive** `refresh_token` in `secret.json`. Poi esegui `terraform apply` per aggiornare la Lambda.

### Altre modalità

- [OAuth 2.0 Playground](https://developers.google.com/oauthplayground/) con scope personalizzati (redirect del Playground se usi le sue credenziali).
- Flussi OAuth manuali che scambiano `code` → token.

Conserva il **refresh token** come una password; non committarlo.

---

## Deploy con Terraform (state locale)

Lo **state Terraform** è configurato come **backend locale** nel file `terraform/terraform.tfstate` (non usare backend remoto a meno di modificarlo).

Dalla cartella `terraform/`:

```bash
terraform init
terraform plan
terraform apply
```

- Regione predefinita: `eu-south-1` (modificabile con variabile `aws_region`).
- Il file `.terraform.lock.hcl` va versionato insieme al codice per ripetibilità.

Variabili utili (vedi `terraform/variables.tf`):

| Variabile | Significato |
| --- | --- |
| `lambda_timeout` | Timeout massimo (secondi); default 900 (15 min). |
| `max_poll_seconds` | Quanto attendere il completamento del job nell’azione `export`. |
| `poll_interval_sec` | Intervallo tra due controlli di stato. |
| `organize_origin_address` | Indirizzo di partenza per le distanze (testo, mostrato in output). |
| `organize_origin_lat` / `organize_origin_lon` | Coordinate WGS84 dell’origine: se entrambe valorizzate, **non** si usa Nominatim per l’origine (consigliato: da IP AWS Nominatim spesso fallisce). |
| `organize_city_filter` | Hint città per il geocoding Nominatim dei singoli luoghi. |
| `organize_nominatim_user_agent` | User-Agent verso Nominatim (inserisci un contatto realistico). |

Prima del **primo** `terraform apply`, genera il bundle Python della seconda Lambda (dipendenze `geopy`):

```bash
python lambda_organize/build.py
```

Ripeti dopo modifiche a `lambda_organize/lambda_function.py` o `requirements.txt` (o lancia `terraform apply`: il `null_resource` riesegue `build.py` quando cambiano gli hash).

---

## Step Functions (export → organize)

È inclusa una state machine **STANDARD** (`{project_name}-pipeline`):

1. **`ExportTakeout`** — invoca la Lambda Data Portability con `Payload = $.export_request` (stesso formato degli esempi `export-*.json` ma annidato sotto `export_request`).
2. **`OrganizePlaces`** — passa alla seconda Lambda `takeout = Payload della prima` (l’output completo con `downloads`). L’indirizzo origine per le distanze è **`ORIGIN_ADDRESS`** impostato da Terraform sulla Lambda organize.
3. **`FormatOutput`** — espone come output dell’esecuzione solo il JSON restituito dall’organize (`origin`, `count`, `places`, `meta`).

Input esempio: `examples/step-function-input.json`.

Dopo `terraform apply`, dalla **root del repo** (PowerShell):

```powershell
.\scripts\run_step_function_sync.ps1
```

Lo script legge l’ARN con `terraform output -raw state_machine_arn`, la regione dall’ARN (o `eu-south-1`), esegue `start-execution`, attende `SUCCEEDED` con `describe-execution` e scrive il risultato in **`out.json`**. Opzioni: `-Region`, `-StateMachineArn`, `-InputFile`, `-OutFile`.

(`start-sync-execution` è solo per state machine **EXPRESS**, non per questa pipeline **STANDARD**.)

**Limiti:** Step Functions e Lambda hanno limiti di dimensione sul payload; export molto grandi possono fallire senza passaggio intermedio su **S3**.

**Override** `origin_address` / `city_filter`: invocando **direttamente** la Lambda `…-organize` (non via Step Functions) puoi passare nel body `takeout`, `origin_address`, `city_filter` come nel codice di `lambda_organize/lambda_function.py`.

---

## Invocare la Lambda

Payload di esempio (liste salvate Search/Maps):

```json
{
  "action": "export",
  "resources": ["saved.collections"]
}
```

Solo luoghi “starred” su Maps:

```json
{
  "action": "export",
  "resources": ["maps.starred_places"]
}
```

**Azioni supportate**

| `action` | Comportamento |
| --- | --- |
| `export` | `initiate` → polling fino a `COMPLETE` → download e parsing CSV da ZIP. |
| `initiate` | Solo avvio job; risposta con `archiveJobId`. |
| `poll` | Legge lo stato; richiede `job_id`. |
| `download` | Scarica e parsa se lo stato è `COMPLETE`; richiede `job_id`. |

Esempio AWS CLI:

```bash
aws lambda invoke ^
  --function-name gmaps-dataportability ^
  --cli-binary-format raw-in-base64-out ^
  --payload file://examples/export-saved-collections.json ^
  out.json
```

Se il job supera `MAX_POLL_SECONDS`, la Lambda restituisce errore di timeout: usa `initiate` + `poll` + `download` in momenti separati o aumenta timeout e limiti di polling.

**Limite:** l’invocazione sincrona Lambda ha un tetto di dimensione della risposta (ordine di **6 MB**). Export molto grandi potrebbero richiedere di salvare l’output su S3 in una evoluzione del codice.

---

## Riferimenti API

- [Metodi (initiate, getPortabilityArchiveState, …)](https://developers.google.com/data-portability/user-guide/methods)
- [Schema Saved (`saved.collections`)](https://developers.google.com/data-portability/schema-reference/save)
- [REST `portabilityArchive.initiate`](https://developers.google.com/data-portability/reference/rest/v1/portabilityArchive/initiate)

---

## Struttura repository

- `lambda/handler.py` — logica OAuth, job di export, download e parsing CSV.
- `lambda_organize/` — seconda Lambda (geopy/Nominatim): organizza i luoghi e le distanze.
- `scripts/get_refresh_token.py` — ottiene il refresh token e aggiorna `secret.json`.
- `scripts/run_step_function_sync.ps1` — esegue la pipeline Step Functions e scrive `out.json`.
- `terraform/` — due Lambda, Step Functions, IAM, env da `secret.json`, **backend locale**.
