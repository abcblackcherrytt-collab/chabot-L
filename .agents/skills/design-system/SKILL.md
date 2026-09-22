---
name: chabot-design-system
description: Use when designing or revising Chabot web pages, plan-selection screens, checkout entry pages, admin UI, or other user-facing layouts. Routes the task to the appropriate style references under this skill and requires an accessible, responsive design decision before implementation.
---

# Chabot Design System

Use this skill whenever the user asks for a design change, layout adjustment, visual refinement, or UI polish in the Chabot project.

## Design intent

Create a trustworthy, calm, professional interface for a healthcare-oriented service. Prioritize comprehension and safe action over decoration: a user must understand what a page is for, what choices mean, and what happens after tapping the primary action.

## Required workflow

1. Inspect the existing page, route behavior, content, and repository conventions before changing the UI.
2. Choose the smallest fitting style set from `references/style-skills/`:
   - `clean`, `minimal`, `simple`, or `spacious` for utility-first pages.
   - `professional`, `premium`, `elegant`, or `refined` for paid plans, checkout, and trust-sensitive flows.
   - `friendly`, `cafe`, or `soft`-adjacent styles only when the existing brand clearly supports a warmer tone.
   - `bold`, `brutalism`, `neon`, `retro`, and other expressive styles require an explicit user request or strong existing brand evidence.
3. Read the selected child `SKILL.md` files before deciding tokens, typography, spacing, and component treatment. Do not load every reference by default.
4. State the design decision briefly in the work log/commentary, then implement it without changing unrelated business logic or payment/authentication behavior.
5. Verify semantic HTML, responsive behavior, keyboard focus, touch target size, contrast, reduced-motion behavior, and the existing relevant tests.
6. Update `PROJECT_PLAN.md` after implementation, clearly distinguishing local verification from production deployment.

## Chabot baseline constraints

- Use a restrained palette with one primary accent and neutral surfaces; avoid visual noise and gratuitous gradients.
- Use a 4/8-point spacing rhythm and preserve a clear heading → explanation → choice/action hierarchy.
- Make primary actions explicit and descriptive. A whole card may be clickable only when its destination is unambiguous.
- Keep interactive targets at least 44px high/wide. Provide a visible `:focus-visible` state; never remove the outline without an equivalent.
- Support narrow mobile layouts first, then enhance to multi-column layouts at wider breakpoints.
- Respect `prefers-reduced-motion: reduce` and avoid motion that is required to understand the page.
- Keep user-facing copy concise, friendly, and low-jargon. Do not invent pricing, limits, tax treatment, or product claims; use the project source of truth.
- For payment pages, preserve the existing Stripe host validation, auth redirects, success/cancel routes, and no-store behavior.

## Routing references

The source style library is preserved as child skills so future design work can select a coherent direction without rediscovering the original guidance:

- [clean](references/style-skills/clean/SKILL.md), [spacious](references/style-skills/spacious/SKILL.md), [minimal](references/style-skills/minimal/SKILL.md): clarity and layout foundations.
- [professional](references/style-skills/professional/SKILL.md), [premium](references/style-skills/premium/SKILL.md), [elegant](references/style-skills/elegant/SKILL.md): trust-sensitive paid and account flows.
- [friendly](references/style-skills/friendly/SKILL.md), [modern](references/style-skills/modern/SKILL.md), [refined](references/style-skills/refined/SKILL.md): optional tone and polish variants.
- Other style directories in `references/style-skills/` are available only when the request or existing brand calls for them.

Do not copy a complete child skill into the parent. Read only the references needed for the current design decision.
