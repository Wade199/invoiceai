# THREAT_MODEL.md — Modèle de menaces

> Projet : [NOM DU PROJET]
> Dernière mise à jour : [DATE]
> Statut : [Draft / Validé / À réviser]

---

## 🎯 Actifs critiques

| Actif | Description | Valeur | Localisation |
|-------|-------------|--------|--------------|
| [Ex: BDD users] | Données utilisateurs | Critique | PostgreSQL privé |
| [Ex: API keys] | Clés d'accès services tiers | Critique | Vault |
| [Ex: Fichiers uploads] | Documents clients | High | S3 privé |

---

## 👥 Utilisateurs & Privilèges

| Rôle | Accès | Niveau de confiance |
|------|-------|---------------------|
| Administrateur | Accès total | Élevé — compte séparé |
| Utilisateur authentifié | Accès à ses données | Moyen |
| Utilisateur anonyme | Accès public uniquement | Faible |
| Service interne | Accès inter-services | Moyen — credentials rotatifs |

---

## 🚪 Points d'entrée

| Point d'entrée | Exposition | Authentification | Validation |
|----------------|------------|-----------------|------------|
| API REST /api/* | Internet | JWT | Oui |
| Interface admin /admin | VPN uniquement | MFA | Oui |
| Webhooks /webhook/* | Internet | HMAC signature | Oui |
| BDD PostgreSQL | Interne uniquement | Password + SSL | N/A |

---

## ⚠️ Menaces identifiées

### CRITICAL

| # | Menace | Vecteur | Probabilité | Impact | Prévention | Détection | Récupération |
|---|--------|---------|-------------|--------|------------|-----------|--------------|
| T01 | Injection SQL | Input API non validé | Med | Critique | ORM + validation | WAF + logs | Backup + patch |
| T02 | Fuite de secrets | Secret dans Git | Low | Critique | Secret scanning CI | GitLeaks | Révoquer + remplacer |

### HIGH

| # | Menace | Vecteur | Probabilité | Impact | Prévention | Détection | Récupération |
|---|--------|---------|-------------|--------|------------|-----------|--------------|
| T03 | Brute force auth | API login | High | High | Rate limiting + lockout | Alerte tentatives | Reset forcé |
| T04 | XSS stocké | Champ texte | Med | High | Sanitisation output | CSP headers | Purge données |

### MEDIUM

| # | Menace | Vecteur | Probabilité | Impact | Prévention | Détection | Récupération |
|---|--------|---------|-------------|--------|------------|-----------|--------------|
| T05 | CSRF | Formulaire | Med | Med | Token CSRF | Logs requêtes | Invalider sessions |

### LOW / INFORMATIONAL

| # | Menace | Vecteur | Notes |
|---|--------|---------|-------|
| T06 | Information disclosure | Erreurs trop détaillées | Filtrer les messages d'erreur en prod |

---

## 📊 Résumé des risques

| Niveau | Nombre | Statut |
|--------|--------|--------|
| CRITICAL | X | X traités / X restants |
| HIGH | X | X traités / X restants |
| MEDIUM | X | X traités / X restants |
| LOW | X | X traités / X restants |

---

## 🔄 Historique des révisions

| Date | Modification | Auteur |
|------|-------------|--------|
| [DATE] | Création initiale | Jarvis |
