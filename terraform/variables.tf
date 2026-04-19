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
