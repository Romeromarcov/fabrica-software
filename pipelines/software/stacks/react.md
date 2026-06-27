## Estructura
Estructura React + TypeScript: `src/types/[modulo].ts`, `src/services/[modulo]Service.ts`, `src/hooks/use[Feature].ts` (TanStack Query), `src/components/[Feature]/`, `src/pages/[Feature]Page.tsx`. Nunca usar `any`. Nunca usar `useEffect` para fetching de datos.

## Imports
import React from 'react';
import { useQuery } from '@tanstack/react-query';

## Testing
Vitest + Testing Library para componentes.

## QA
Tests de frontend:
1. Render sin crash (snapshot o RTL)
2. Loading state
3. Error state
4. Interacciones de usuario (click, submit)
5. Datos vacíos
Usar: Vitest, @testing-library/react
