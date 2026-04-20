variable "aws_region" {
  type        = string
  description = "Regione AWS per Lambda."
  default     = "eu-south-1"
}

variable "google_oauth_json_file" {
  type        = string
  description = "Percorso al secret.json (relativo alla cartella terraform/ se usi un path relativo)."
  default     = "../secret.json"
}

variable "project_name" {
  type        = string
  description = "Prefisso per nomi risorse."
  default     = "gmaps-dataportability"
}

variable "lambda_timeout" {
  type        = number
  description = "Timeout Lambda in secondi (export completo può richiedere diversi minuti)."
  default     = 900
}

variable "lambda_memory_mb" {
  type        = number
  description = "Memoria allocata alla Lambda."
  default     = 256
}

variable "poll_interval_sec" {
  type        = string
  description = "Intervallo tra due GET dello stato job (export)."
  default     = "30"
}

variable "max_poll_seconds" {
  type        = string
  description = "Attesa massima per il completamento export (poi TimeoutError; usa poll manuale)."
  default     = "840"
}

variable "organize_lambda_timeout" {
  type        = number
  description = "Timeout Lambda organize (geocoding Nominatim può richiedere molto tempo)."
  default     = 900
}

variable "organize_lambda_memory_mb" {
  type        = number
  description = "Memoria Lambda organize."
  default     = 512
}

variable "organize_origin_address" {
  type        = string
  description = "Indirizzo origine per le distanze (env ORIGIN_ADDRESS sulla seconda Lambda)."
  default     = "Via Apuania 16, Roma"
}

variable "organize_city_filter" {
  type        = string
  description = "Suggerimento città per geocoding luoghi (env CITY_FILTER)."
  default     = "roma"
}

variable "organize_nominatim_user_agent" {
  type        = string
  description = "User-Agent obbligatorio per Nominatim (politica di utilizzo)."
  default     = "gmaps-dataportability-organize/1.0 (contact: you@example.com)"
}

variable "organize_origin_lat" {
  type        = string
  description = "Latitudine origine (WGS84). Se valorizzata insieme a organize_origin_lon, salta il geocoding (consigliato su Lambda)."
  default     = ""
}

variable "organize_origin_lon" {
  type        = string
  description = "Longitudine origine (WGS84)."
  default     = ""
}
