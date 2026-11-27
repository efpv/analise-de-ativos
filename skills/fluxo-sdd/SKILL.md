---
name: fluxo-sdd
description: >
  SDD workflow orchestration: Specification-Driven Development flow. Guides implementation
  through human-validated spec artifacts (tarefa → PRD → spec → code).
  Guarantees no implementation without approved specification. Maintains traceability
  between task, PRD, spec, and code. Triggers: "fluxo sdd", "executar fluxo", "sdd workflow",
  "spec-driven development", "iniciar sdd".
---

# Fluxo SDD (Specification-Driven Development)

## Objetivo

Garantir que implementação começa **só após validação humana** dos artefatos de especificação.

**Gatekeep:** Não implementar sem spec aprovada. Não inventar requisitos. Registrar ambiguidades.

---

## Sequência de 9 Etapas

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. PREPARAR: Atualizar doc-specs/tarefa.txt                     │
│    ├─ Contexto: o que é?                                       │
│    ├─ Requisitos: o que fazer?                                 │
│    └─ Restrições: limites, regras, compliance                  │
├─────────────────────────────────────────────────────────────────┤
│ 2. PLANEJAR: @sddPlanner planejar                              │
│    └─ Output: PRD outline, abduções, roadmap                   │
├─────────────────────────────────────────────────────────────────┤
│ ⭐ REVISAR 1: doc-specs/tarefa.md (humano)                      │
│    └─ Confirmar: escopo OK? Ambiguidades? Restrições claras?   │
├─────────────────────────────────────────────────────────────────┤
│ 4. GERAR PRD: @sddPlanner gerarPRD                             │
│    └─ Output: doc-specs/prd.md (Product Requirements)          │
├─────────────────────────────────────────────────────────────────┤
│ ⭐ REVISAR 2: doc-specs/prd.md (humano)                         │
│    └─ Confirmar: features claras? Aceitação OK? Mockups?       │
├─────────────────────────────────────────────────────────────────┤
│ 6. GERAR SPEC: @sddPlanner gerarSpec                           │
│    └─ Output: doc-specs/spec.md (Technical Specification)      │
├─────────────────────────────────────────────────────────────────┤
│ ⭐ REVISAR 3: doc-specs/spec.md (humano) — CRITICAL            │
│    └─ Confirmar: arquitetura? APIs? BD? Sem ambiguidades?      │
├─────────────────────────────────────────────────────────────────┤
│ 8. IMPLEMENTAR: @sddImplementer implementar                     │
│    └─ Output: código, testes, artefatos (apenas SEM PRD/spec)  │
├─────────────────────────────────────────────────────────────────┤
│ 9. REVISAR CÓDIGO: @sddReviewer revisar                         │
│    └─ Output: PR review, gaps, correções                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Invocações

### Iniciar Fluxo

```
@fluxo-sdd iniciar
```

Checa tarefa.md, pronto para etapa 2.

### Etapa 2: Planejar

```
@sddPlanner planejar
```

Lê `doc-specs/tarefa.md` → gera outline PRD.

### Etapa 4: Gerar PRD

```
@sddPlanner gerarPRD
```

Salva `doc-specs/prd.md` completo.

### Etapa 6: Gerar Spec

```
@sddPlanner gerarSpec
```

Salva `doc-specs/spec.md` técnico + sem ambiguidades.

### Etapa 8: Implementar

```
@sddImplementer implementar
```

Lê spec.md, gera código com TDD + requirement traceability.

### Etapa 9: Revisar

```
@sddReviewer revisar
```

Revisa código contra spec + PRD, gera PR comments.

---

## Princípios (Gatekeeping)

| Princípio             | Ação                                              |
| --------------------- | ------------------------------------------------- |
| **Spec-First**        | Não code sem spec.md aprovada                     |
| **Human in the Loop** | Revisor humano em 3, 5, 7 antes de impl           |
| **Rastreabilidade**   | Todo código linkedado a REQ-XXX                   |
| **Sem Invenção**      | Apenas req de tarefa.md / prd.md / spec.md        |
| **Ambiguidades**      | Registrar em spec.md como `[NEEDS CLARIFICATION]` |

---

## Artefatos Esperados

### Tarefa (1º)

**Arquivo:** `doc-specs/tarefa.txt` ou `doc-specs/tarefa.md`

```md
# Tarefa: [Título]

## Contexto

[O que é? Por quê?]

## Requisitos

- REQ-1: [o quê]
- REQ-2: [o quê]

## Restrições

- [Compliance, tech stack, etc]
```

### PRD (4º)

**Arquivo:** `doc-specs/prd.md`

```md
# Product Requirements Document

## Visão Geral

[Summary]

## Features

- FEAT-1: [user story]
- FEAT-2: [user story]

## Critérios de Aceitação

[Acceptance per feature]

## Mockups / Wireframes

[Links or embedded]
```

### Spec (6º)

**Arquivo:** `doc-specs/spec.md`

```md
# Especificação Técnica

## Arquitetura

[Sistema, fluxo, componentes]

## APIs / Endpoints

[Contratos]

## BD / Schema

[DDL, indices, RLS]

## Código

[Classes, functions, estrutura]

## Sem Ambiguidades

[SE algo não está claro: `[NEEDS CLARIFICATION]`]
```

---

## Exemplo: Tarefa → PRD → Spec → Code

### 1️⃣ Tarefa

```md
# Tarefa: API de Listagem de Clientes

## Contexto

Plataforma SaaS Gestão de Festas. Multi-tenant.

## Requisitos

- REQ-1: GET /api/customers (com pagination)
- REQ-2: Filtrar por tenant_id (RLS)
- REQ-3: Retornar JSON { id, name, email, phone }

## Restrições

- FastAPI + SQLAlchemy
- PostgreSQL 16, RLS obrigatório
- usuário_integracao (DML-only)
```

### 2️⃣ PRD

```md
# PRD: Listar Clientes

## Feature: List Customers

- User story: "Como admin de tenant, quero ver lista de clientes"
- Acceptance: GET /api/customers?page=1&limit=10 → list + total

## Mockup

[JSON mock]
```

### 3️⃣ Spec

```md
# Spec: GET /api/customers

## Endpoint
```

GET /api/customers?page=1&limit=10
Authorization: Bearer JWT

Response 200:
{
"data": [
{ "id": "uuid", "name": "...", "email": "...", "phone": "..." }
],
"total": 42,
"page": 1
}

```

## BD Query
SELECT * FROM customers WHERE tenant_id = current_app_tenant_id()

## Sem Ambiguidades
✓ RLS handled by DB policy
✓ Pagination in app (offset/limit)
```

### 4️⃣ Code

```python
@router.get("/api/customers")
async def list_customers(
    page: int = 1,
    limit: int = 10,
    session: AsyncSession = Depends(get_db)
):
    # TDD: test first
    # Requirement traceability: REQ-1, REQ-2, REQ-3

    offset = (page - 1) * limit
    result = await session.execute(
        select(Customer)
        .where(Customer.tenant_id == current_tenant_id())
        .offset(offset)
        .limit(limit)
    )
    ...
```

---

## Human Review Points (⭐)

### Etapa 3: Revisar Tarefa

- [ ] Escopo claro?
- [ ] Requisitos bem-definidos?
- [ ] Restrições (compliance, tech) documentadas?
- [ ] Alguma ambiguidade?

**Ação:** Editar tarefa.md ou prosseguir → PRD.

### Etapa 5: Revisar PRD

- [ ] Features claras?
- [ ] Acceptance criteria unambíguo?
- [ ] Mockups/wireframes inclusos?
- [ ] Priorização clara (MVP vs nice-to-have)?

**Ação:** Revisar prd.md ou prosseguir → Spec.

### Etapa 7: Revisar Spec (CRITICAL)

- [ ] Arquitetura clara?
- [ ] APIs bem contratadas (request/response)?
- [ ] BD schema e RLS definido?
- [ ] Sem `[NEEDS CLARIFICATION]`?
- [ ] Código estrutura clara?

**Ação:** Revisar spec.md ou voltar → PRD ajuste.

---

## Workflow: Se Encontrar Ambiguidade

1. **Em tarefa.md:** Bloqueia fluxo. Edit tarefa → reinicia planejar
2. **Em prd.md:** Bloqueia fluxo. Edit prd → regenera spec
3. **Em spec.md:** Marca `[NEEDS CLARIFICATION] ...` e bloqueia impl
   - Retorna para revisor
   - Revisor clarifica → re-runnya gerarSpec
   - **Nunca** implementar com spec incompleta

---

## Integração com Git/PR

Após implementação (etapa 8):

1. Código commitado em feature branch (ex: `feature/list-customers`)
2. Etapa 9: @sddReviewer gera PR review comments
3. PR linkedado a task (`closes #123`)
4. Merge apenas com aprovação + sem gaps

---

## Checklist de Conclusão

Antes de considerar task "Done":

- [ ] Tarefa.md aprovada (sem ambiguidades)
- [ ] PRD.md aprovada (features OK)
- [ ] Spec.md aprovada (SEM `[NEEDS CLARIFICATION]`)
- [ ] Código implementado (reflete 100% spec)
- [ ] Testes passando (TDD coverage ≥ 80%)
- [ ] PR merged
- [ ] Aprendizados registrados (sharing-learnings)

---

## Princípios + Boundary Rules

- **No Spec → No Code.** Implementer recusa se spec incompleta.
- **Rastreabilidade Obrigatória.** Cada linha de código = REQ-X.
- **Revisor Humano = Gatekeeper.** Revisor aprova PRD/spec ou rejeita.
- **Ambiguidade = Bloqueio.** Spec com `[NEEDS CLARIFICATION]` não sai de gatekeeping.
- **Iteração Rápida.** Planejar → PRD → Spec em 1-2h. Impl após aprovação.

---

## Exemplos de Invocação

### Iniciar do zero

```
User: "Fluxo SDD para API de clientes"
→ @fluxo-sdd iniciar
→ Checa tarefa.md, pronto para etapa 2
→ User revisa tarefa.md
→ User: "aprova tarefa"
→ @sddPlanner planejar
→ User revisa prd outline
→ @sddPlanner gerarPRD
→ ... (loop até spec.md OK)
→ @sddImplementer implementar
→ @sddReviewer revisar
```

### Resumir status atual

```
User: "Onde estou no fluxo?"
→ Skill: "Etapa 6. Spec.md gerado. Aguardando revisão humana."
→ User revisa spec.md
→ User: "spec OK, implementar"
→ @sddImplementer implementar
```

---

## Não Fazer

❌ Implementar sem spec.md  
❌ Escrever spec sem PRD  
❌ Escrever PRD sem tarefa.md clara  
❌ Ignorar `[NEEDS CLARIFICATION]`  
❌ Saltare reviews humanas  
❌ Inventar requisitos fora de tarefa/PRD/spec

---

## Referências Internas

- `docs/fluxo-sdd.md` — Overview workflow
- `doc-specs/tarefa.txt` — Current task definition
- `doc-specs/prd.md` — Product requirements (se existe)
- `doc-specs/spec.md` — Technical specification (se existe)
- Skills relacionadas: `create-specification`, `implementing-code`, etc.
