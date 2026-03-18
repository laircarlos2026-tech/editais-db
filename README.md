# Seletor de Editais — Base de Dados

Este repositório mantém a base de editais atualizada automaticamente toda semana via GitHub Actions.

## Configuração (primeira vez)

### 1. Criar o repositório no GitHub
- Crie um repositório público (ex: `editais-db`)
- Suba todos estes arquivos

### 2. Configurar os Secrets
Vá em **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Como obter |
|--------|-----------|
| `SITE_NONCE` | Abra o site → F12 → Console → digite `LC_SAAS.nonce` |
| `SITE_COOKIE` | F12 → Application → Cookies → copie o valor do cookie `wordpress_logged_in_*` |

> ⚠️ O nonce e o cookie expiram. Se o download parar de funcionar, atualize os secrets.

### 3. Rodar manualmente pela primeira vez
- Vá em **Actions → Atualizar base de editais → Run workflow**

### 4. Configurar a extensão
No `content.js` da extensão, defina a URL do seu repositório:

```javascript
const EDITAIS_DB_URL = 'https://raw.githubusercontent.com/SEU-USUARIO/editais-db/main/data/editais.json';
const EDITAIS_META_URL = 'https://raw.githubusercontent.com/SEU-USUARIO/editais-db/main/data/meta.json';
```

## Agendamento

O workflow roda automaticamente **todo domingo às 03:00 BRT**.

Para mudar o horário, edite o cron em `.github/workflows/update-editais.yml`:
```yaml
- cron: '0 6 * * 0'  # domingo 06:00 UTC = 03:00 BRT
```

## Estrutura dos arquivos

### `data/editais.json`
Array de editais com os campos:
```json
[
  {
    "id": 710883,
    "objeto": "Contratação de empresa...",
    "cidade": "Teresina",
    "uf": "PI",
    "abertura": "17/03/2026 00:00:00",
    "valor": 1473662.12,
    "modalidade": "Concorrência - Eletrônica",
    "orgao": "SECRETARIA ESTADUAL DE DEFESA CIVIL",
    "edital": "08789777000199-1-000010/2026",
    "plataforma": "BNC"
  }
]
```

### `data/meta.json`
Metadados da última atualização:
```json
{
  "updated_at": "2026-03-16T06:00:00+00:00",
  "total": 8432,
  "days_back": 60,
  "date_from": "2026-01-15",
  "version": "20260316"
}
```
