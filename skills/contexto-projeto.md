```markdown
# Contexto do Projeto — Gestão de Festas

> Este arquivo deve ser usado como **contexto padrão** por todos os agentes do Copilot Chat.
> Só abra `../docs/GestaoDeFestas-Guia-Desenvolvimento.md` na íntegra se a
> pergunta exigir um detalhe (DDL completa, código de exemplo, etc.) que
> não está coberto aqui.

## O que é
SaaS multi-tenant de gestão para empresas de decoração de festas: cadastro de clientes,
orçamentos/reservas, contratos com assinatura digital, controle de estoque e automação
via WhatsApp.

## Stack
- **Backend:** Python 3.12+ / FastAPI (async) / SQLAlchemy 2.0 + Alembic
- **Banco:** PostgreSQL 16 (self-hosted, container próprio — sem Supabase)
- **Frontend:** React + Vite + TypeScript, PWA (manifest + service worker)
- **Auth:** JWT próprio (PyJWT) + Passlib/bcrypt — sem provedor externo
- **Mensageria:** Evolution API (WhatsApp)
- **Integrações externas:** ViaCEP (endereço), BrasilAPI/ReceitaWS (CNPJ)
- **Deploy:** Docker + Docker Compose (Linux), containers de api/frontend/db integrados

## Arquitetura: Clean Architecture + SOLID
```
app/
  domain/          → entidades puras, value objects, interfaces (ABC) de repositório/serviço
  application/     → use cases (orquestram fluxos), DTOs em Pydantic
  infrastructure/  → SQLAlchemy, rotas FastAPI, JWT, integrações externas (ViaCEP, BrasilAPI, Evolution API)
```
Regra: `domain` e `application` nunca importam nada de `infrastructure`.

## Multi-tenancy
- Toda tabela relevante tem `tenant_id` + Row Level Security (RLS) no Postgres.
- API seta `SET LOCAL app.tenant_id` e `SET LOCAL app.user_id` a cada requisição, com base nas claims do JWT.
- Auditoria (`created_by`/`updated_by`) resolvida via trigger + função `current_app_user_id()`.

## Papéis (roles)
`SUPER_ADMIN` → `TENANT_ADMIN` → `TENANT_OPERATOR` → `Cliente Final`.

## Tabelas principais
`tenants`, `users`, `customers`, `dependents`, `inventory_items`, `themes`, `theme_items`,
`rentals`, `contracts`.

## LGPD
- Dados de `dependents` exigem consentimento do responsável.
- Contratos assinados não podem ser deletados → anonimizar, não excluir.
- CPF e hash de auditoria do contrato nunca são anonimizados.

## Decisões em aberto (#decision-open)
- Paleta de cores oficial não definida.
- RLS só aplicado em `customers` — falta replicar.
- Política de expiração de convite/senha não definida.
- Modelo de monetização ainda não definido.

## Convenções de código
- Arquivos em `snake_case`, classes em `PascalCase`.
- DTOs com `pydantic.BaseModel`.
- Interfaces no `domain` com `ABC` + `abstractmethod`.
- Testes: `pytest` + `pytest-asyncio`.

---

## Skills disponíveis (skills/)

### Banco de dados
- `postgresql-code-review` — revisar DDL/migrations.
- `postgresql-optimization` — otimizar queries/índices.
- `sql-code-review` / `sql-optimization` — SQL geral.

### Arquitetura e decisões
- `create-architectural-decision-record` — gerar ADRs.
- `architecture-blueprint-generator` — mudanças estruturais.
- `technology-stack-blueprint-generator` — mudanças de stack.
- `create-specification` / `create-implementation-plan` — iniciar fases do backlog.

### Documentação
- `create-readme` / `documentation-writer`.

### LGPD e segurança
- `gdpr-compliant` — checklist LGPD.
- `security-review` — revisar endpoints.
- `secret-scanning` — evitar vazamento de segredos.

### Git e CI/CD
- `conventional-commit` / `git-commit` / `gitmoji`.
- `github-actions-hardening` / `github-actions-efficiency`.
- `multi-stage-dockerfile`.

### Testes
- `pytest-coverage` — revisar cobertura.
- `webapp-testing` — testes end-to-end.

### Frontend
- `anti-ui-slop` / `web-design-reviewer`.

### Aprendizado
- `mentoring-juniors` / `add-educational-comments`.

---

## Economia de tokens (skill caveman)

- **Usar caveman automaticamente** em revisões de código, comandos diretos, confirmações de status e tarefas técnicas/mecânicas.
- **Não usar caveman** em explicações de arquitetura, ADRs, LGPD/segurança e respostas de mentoria.
- Na dúvida, perguntar ao usuário o nível de detalhe desejado antes de aplicar caveman.

> Regra geral: se a tarefa corresponde a uma das skills listadas, use a skill correspondente antes de responder.  
> Para tarefas técnicas mecânicas, combine com **caveman** para reduzir tokens; para explicações e decisões, priorize clareza.
```