# SECURITY_CHECKLIST.md — Checklist avant release

> À passer OBLIGATOIREMENT avant chaque mise en production.
> Projet : [NOM] | Version : [vX.X.X] | Date : [DATE]

---

## 🏗️ Architecture & Réseau

- [ ] Aucune BDD exposée directement sur Internet
- [ ] Segmentation réseau en place (frontend / backend / db séparés)
- [ ] TLS configuré et valide sur tous les endpoints publics
- [ ] Ports inutiles fermés
- [ ] Interface d'administration non accessible depuis Internet
- [ ] Rate limiting actif sur les endpoints publics
- [ ] WAF configuré (si applicable)

---

## 🔐 Authentification & Autorisation

- [ ] MFA activé sur les comptes admin
- [ ] Mots de passe forts imposés
- [ ] Tokens avec expiration configurée
- [ ] Sessions invalidées à la déconnexion
- [ ] Politique de lockout sur tentatives multiples
- [ ] Principe du moindre privilège appliqué
- [ ] Comptes de service avec permissions minimales
- [ ] Accès admin tracé et auditable

---

## 🔑 Secrets

- [ ] Aucun secret dans le code source
- [ ] Aucun secret dans l'historique Git (`git log` vérifié)
- [ ] Variables d'environnement sécurisées en prod
- [ ] Secrets différents entre dev / staging / prod
- [ ] Secret scanning activé dans le CI/CD
- [ ] Processus de rotation des credentials documenté

---

## 🌐 Application Web / API (OWASP)

- [ ] Inputs validés côté serveur (pas seulement côté client)
- [ ] Requêtes SQL via ORM ou requêtes préparées (pas de concaténation)
- [ ] Outputs encodés pour prévenir le XSS
- [ ] Protection CSRF en place
- [ ] Headers de sécurité configurés (CSP, HSTS, X-Frame-Options...)
- [ ] Messages d'erreur ne révèlent pas d'informations sensibles en prod
- [ ] File upload : type, taille et contenu vérifiés
- [ ] SSRF : URLs externes filtrées et validées
- [ ] Accès aux ressources vérifié (IDOR non possible)

---

## 📦 Dépendances

- [ ] `npm audit` / `pip-audit` / `trivy` exécuté sans vulnérabilité CRITICAL ou HIGH non traitée
- [ ] Lockfile à jour et committé
- [ ] Dépendances inutilisées supprimées
- [ ] Images Docker basées sur des images officielles et à jour

---

## 🔄 CI/CD

- [ ] Secret scanning intégré dans le pipeline
- [ ] Dependency scanning intégré
- [ ] Tests automatiques passent à 100%
- [ ] Branches protégées (merge impossible sans review)
- [ ] Artefacts de build contrôlés et reproductibles

---

## 📊 Logs & Monitoring

- [ ] Événements de sécurité loggés (auth, admin, erreurs)
- [ ] Aucun mot de passe / token dans les logs
- [ ] Alertes configurées (brute force, erreurs critiques)
- [ ] Logs centralisés et accessibles
- [ ] Durée de rétention des logs définie

---

## 💾 Données & Backup

- [ ] Données sensibles chiffrées au repos
- [ ] Chiffrement en transit (TLS)
- [ ] Sauvegardes automatisées et testées
- [ ] Accès aux sauvegardes restreint
- [ ] Procédure de restauration documentée et testée

---

## 🌍 Configuration des environnements

- [ ] Variables de prod différentes du dev
- [ ] Debug / stack traces désactivés en production
- [ ] Logs de debug désactivés en production
- [ ] Configuration externalisée (pas dans le code)

---

## 📋 Security Gate — Synthèse finale

```
SECURITY STATUS — [NOM PROJET] v[X.X.X]

Attack surface    : ✅ / ⚠️ / ❌  [commentaire]
Authentication    : ✅ / ⚠️ / ❌  [commentaire]
Authorization     : ✅ / ⚠️ / ❌  [commentaire]
Secrets           : ✅ / ⚠️ / ❌  [commentaire]
Input validation  : ✅ / ⚠️ / ❌  [commentaire]
Dependencies      : ✅ / ⚠️ / ❌  [commentaire]
Logging           : ✅ / ⚠️ / ❌  [commentaire]
Monitoring        : ✅ / ⚠️ / ❌  [commentaire]
Backup/Recovery   : ✅ / ⚠️ / ❌  [commentaire]

Known risks       :
  - [Risque 1 — niveau — accepté/à traiter]
  - [Risque 2 — niveau — accepté/à traiter]

Remaining TODOs   :
  - [ ] [Action à faire avant / après release]

Décision          : ✅ GO  /  ❌ NO-GO
```
