## Estructura
Estructura Express/Node: `src/routes/[modulo].ts`, `src/controllers/[modulo].ts`, `src/services/[modulo].ts`, `src/models/[modulo].ts`. Usa middleware para autenticación JWT.

## Imports
import express from 'express';
import { Request, Response } from 'express';

## Testing
Jest con supertest para tests de endpoints.

## QA
Tests obligatorios:
1. Auth middleware (401/403)
2. Happy path de cada ruta
3. Validación de input
4. Manejo de errores (500 controlado)
Usar: Jest, supertest
