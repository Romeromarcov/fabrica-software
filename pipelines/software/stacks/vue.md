## Estructura
Estructura Vue 3 + TypeScript (Composition API): `src/types/[modulo].ts`, `src/composables/use[Feature].ts` (VueQuery o Pinia), `src/components/[Feature].vue`, `src/views/[Feature]View.vue`.

## Imports
import { ref, computed } from 'vue';
import { useQuery } from '@tanstack/vue-query';

## Testing
Vitest + @vue/test-utils.

## QA
Tests de frontend Vue:
1. Render sin crash
2. Props y emits correctos
3. Estados reactivos
Usar: Vitest, @vue/test-utils
