# Google Data Portability API → AWS (Lambda + Step Functions)

Wrapper che usa la [Data Portability API](https://developers.google.com/data-portability/user-guide/overview) di Google per esportare dati Maps (liste salvate, luoghi preferiti), li elabora su AWS e può scrivere i risultati su una pagina **Notion**.

---

## Invocare la pipeline (Step Functions)

La state machine è di tipo **STANDARD**: non usare `start-sync-execution` (è per macchine **EXPRESS**). Per attendere il completamento serve `start-execution` + polling su `describe-execution`.

Dopo aver fatto il deploy con Terraform, dalla **root del repository** (PowerShell):

```powershell
$env:AWS_DEFAULT_REGION = "eu-south-1"   # stessa regione dello state machine
.\scripts\run_step_function_sync.ps1
```

Lo script:

1. Se non imposti `SFN_ARN`, legge l’ARN con `terraform -chdir=terraform output -raw state_machine_arn` (serve la CLI Terraform e uno state già applicato).
2. Imposta la regione di default dall’ARN di Step Functions, altrimenti usa `eu-south-1` o `AWS_DEFAULT_REGION`.
3. Avvia l’esecuzione con `aws stepfunctions start-execution` usando come input predefinito **`examples/step-function-input.json`**.
4. Esegue il polling ogni 10 secondi (parametri `-PollSeconds` e `-TimeoutSeconds` modificabili).
5. Al termine con successo salva l’output in **`out.json`** nella root del repo.

**Parametri utili**

| Parametro | Significato |
| --- | --- |
| `-StateMachineArn` | ARN della state machine (alternativa: variabile d’ambiente `SFN_ARN`). |
| `-Region` | Regione AWS; deve coincidere con la regione dell’ARN. |
| `-InputFile` | JSON di input della pipeline (default: `examples/step-function-input.json`). |
| `-OutFile` | File di output (default: `out.json`). |

**Formato dell’input** (campo obbligatorio `export_request`):

```json
{
  "export_request": {
    "action": "export",
    "resources": ["saved.collections"]
  }
}
```

L’output finale in `out.json` è il payload restituito dall’ultimo passo (**Notion**): ad esempio `ok`, `page_id`, `blocks_appended`, `places_written`.

---

## Installazione e deploy

### Requisiti

- Account **AWS** e [AWS CLI](https://aws.amazon.com/cli/) configurata (`aws configure` o variabili d’ambiente / ruoli).
- [Terraform](https://www.terraform.io/) `>= 1.2`.
- **Python 3** (per gli script di build delle Lambda e, se serve, `scripts/get_refresh_token.py`).

Per la parte Google: progetto Cloud con **Data Portability API** abilitata, schermata di consenso OAuth e client con gli scope `dataportability.*` necessari; un **refresh token** con quegli scope. I dettagli sono nella documentazione ufficiale ([overview](https://developers.google.com/data-portability/user-guide/overview), [Configure OAuth](https://developers.google.com/data-portability/user-guide/configure-oauth)).

### Credenziali Google (`secret.json`)

Copia `secret.json.example` in `secret.json` nella root del repo e compila `client_id`, `client_secret`, `refresh_token`. Per ottenere il refresh token puoi usare `python scripts/get_refresh_token.py` (vedi commenti nello script e URI di redirect `http://127.0.0.1:8090/`). **Non committare** `secret.json`.

### Variabili Terraform (`terraform/terraform.tfvars`)

Copia o crea `terraform/terraform.tfvars` (il file è in `.gitignore`). Indica almeno:

- `google_oauth_json_file` — percorso al `secret.json` (es. `"../secret.json"` dalla cartella `terraform/`).
- Impostazioni per la seconda Lambda (origine, filtri, eventuale chiave Geocoding): vedi `terraform/variables.tf`.
- Per la scrittura su **Notion**: `notion_integration_token` (secret dell’integrazione interna) e `notion_page_id` (ID pagina o URL che contenga l’UUID a 32 caratteri).

In Notion, la pagina deve essere **condivisa con l’integrazione** (o il workspace collegato all’integrazione), altrimenti le chiamate API falliscono anche se il deploy è corretto.

### Terraform e bundle delle Lambda

Dalla cartella `terraform/`:

```bash
terraform init
terraform plan
terraform apply
```

- Lo **state** è **locale** (`terraform/terraform.tfstate` nel backend configurato in `versions.tf`): non versionare il file di state se contiene segreti.
- Prima del primo apply (o dopo modifiche al codice), le cartelle `lambda_organize/build` e `lambda_notion/build` vengono rigenerate dagli `null_resource` che eseguono i rispettivi `build.py`; in alternativa puoi lanciare manualmente `python lambda_organize/build.py` e `python lambda_notion/build.py` dalla root del repo.

Regione predefinita delle risorse: `eu-south-1` (variabile `aws_region`).

---

## Come funziona

### Modello Data Portability

L’API non espone “una lista per ID”: si avvia un job di **archivio** per un *resource group* (es. `saved.collections`), si attende il completamento, poi si scaricano file (CSV/ZIP). I resource group usati sono allineati agli scope OAuth (`dataportability.saved.collections`, `dataportability.maps.starred_places`, …).

### Pipeline Step Functions (`<project_name>-pipeline`)

1. **ExportTakeout** — Invoca la Lambda principale con `Payload = $.export_request` (stesso schema degli esempi `examples/export-*.json`, annidato sotto `export_request`). La Lambda ottiene un access token, avvia il job, attende il completamento e restituisce il takeout con i download analizzati.
2. **OrganizePlaces** — Passa alla seconda Lambda `takeout` = output completo della prima (`$.dataportability_invoke.Payload`). Parsa i CSV, deduplica i luoghi, classifica per area (FID URL), calcola distanze dove possibile, produce un JSON con `origin`, `count`, `places`, `meta`.
3. **FormatOutput** — Estrae solo il payload dell’organize.
4. **WriteNotion** — Invoca la terza Lambda con quel JSON; appende alla pagina Notion un titolo con data, un separatore e un elenco puntato per ogni luogo (link a Maps quando presente).

Variabili d’ambiente sensate per l’organize (origine fissa, modo area `rome`/`all`, ecc.) sono descritte in `terraform/variables.tf` e propagate da Terraform.

### Invocazione diretta della sola Lambda export

Per test senza Step Functions si può usare `aws lambda invoke` con payload come in `examples/export-saved-collections.json` (azioni `export`, `initiate`, `poll`, `download` — vedi tabella nella documentazione inline nel codice `lambda/handler.py`).

---

## Problemi aperti e limitazioni

### Calcolo delle distanze (geocoding)

- La seconda Lambda usa **geopy** con **Nominatim** (OpenStreetMap) per risolvere indirizzi e coordinate. Da **IP AWS**, Nominatim risponde spesso in modo incompleto o instabile; per l’**origine** è più affidabile impostare `organize_origin_lat` e `organize_origin_lon` in `terraform.tfvars` e saltare il geocoding testuale dell’origine.
- Per i **luoghi** presi dal CSV, senza coordinate nell’URL può servire geocoding: lì Nominatim può restituire `null` o risultati scarsi da Lambda.
- Opzionale: `organize_google_geocoding_api_key` (Geocoding API Google) per migliorare il geocoding in cloud; va valutato costo e policy d’uso.
- Le distanze dipendono dalla qualità delle coordinate ottenute: valori `distanza_km` o `indirizzo` assenti non sono necessariamente bug del parser, ma segnalano fallimenti o assenza di dati nel geocoding.

### Data Portability e throttling

- Se Google risponde **409** (job già esistente / finestra temporale tra un export e il successivo), non puoi rilanciare subito un export identico: serve attendere l’indicazione nell’errore o cambiare risorsa/finestra.

### Dimensioni e limiti AWS

- Payload Step Functions e risposta Lambda hanno limiti di dimensione; export molto grandi possono richiedere evoluzioni (es. salvataggio intermedio su **S3**).
- Il refresh token OAuth e il contenuto di `secret.json` finiscono nello **state Terraform locale** se iniettati via variabile: tratta `terraform.tfstate` come sensibile.

### Notion

- La pagina deve essere accessibile all’integrazione. Se la pipeline restituisce successo ma “non vedi nulla”, verifica di essere sulla **pagina corretta**, di aver aggiornato il client dopo un deploy e, in caso di dubbio, i log della Lambda Notion in CloudWatch.

---

## Riferimenti rapidi

| Resource group (API) | Scope OAuth tipico |
| --- | --- |
| `saved.collections` | `https://www.googleapis.com/auth/dataportability.saved.collections` |
| `maps.starred_places` | `https://www.googleapis.com/auth/dataportability.maps.starred_places` |

- [Metodi REST Data Portability](https://developers.google.com/data-portability/user-guide/methods)
- [Schema Saved (`saved.collections`)](https://developers.google.com/data-portability/schema-reference/save)

## Struttura repository

- `lambda/handler.py` — OAuth, job export, download e parsing.
- `lambda_organize/` — organizzazione luoghi e distanze (`geopy` / Nominatim).
- `lambda_notion/` — append blocchi su pagina Notion.
- `scripts/get_refresh_token.py` — refresh token OAuth in `secret.json`.
- `scripts/run_step_function_sync.ps1` — esegue la Step Function e scrive `out.json`.
- `terraform/` — tre Lambda, Step Functions, IAM, variabili sensibili via `*.tfvars`.
