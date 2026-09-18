# INCIDENT_RESPONSE.md — Procédure de réponse aux incidents

> Projet : [NOM DU PROJET]
> Dernière mise à jour : [DATE]

---

## ⚡ Réponse rapide (les 15 premières minutes)

```
1. ISOLER   → Couper l'accès ou le composant compromis si possible
2. ÉVALUER  → Quelle est la gravité ? Quelles données touchées ?
3. RÉVOQUER → Changer les credentials compromis immédiatement
4. ALERTER  → Notifier les personnes concernées
5. LOGGER   → Documenter chaque action avec timestamp
```

---

## 📊 Niveaux de gravité

| Niveau | Description | Délai de réponse |
|--------|-------------|-----------------|
| P1 — Critique | Données compromises, système en panne, ransomware | Immédiat |
| P2 — High | Tentative active, fuite potentielle, service dégradé | < 1h |
| P3 — Medium | Comportement anormal, alerte de monitoring | < 4h |
| P4 — Low | Anomalie mineure, amélioration sécurité | < 48h |

---

## 🔄 Cycle complet de réponse

### 1. DETECTION
- Source de l'alerte : [monitoring / utilisateur / scanner / logs]
- Timestamp de détection : [DATE HEURE]
- Système(s) affecté(s) : [liste]
- Données potentiellement exposées : [oui/non/inconnu]

---

### 2. TRIAGE
- Gravité : [P1 / P2 / P3 / P4]
- Type d'incident : [intrusion / fuite / malware / erreur config / autre]
- Surface touchée : [composants, utilisateurs, données]
- Actif le plus à risque : [...]
- Décision : [contenir / monitorer / escalader]

---

### 3. CONTAINMENT
- [ ] Isoler le composant compromis (réseau, service, compte)
- [ ] Révoquer les credentials compromis ou suspects
- [ ] Bloquer les IPs malveillantes identifiées
- [ ] Désactiver les comptes compromis
- [ ] Capturer les logs et preuves AVANT de modifier quoi que ce soit

> ⚠️ Préserver les preuves avant d'agir si possible.

---

### 4. ERADICATION
- [ ] Identifier la cause racine
- [ ] Supprimer le vecteur d'attaque
- [ ] Patcher la vulnérabilité
- [ ] Supprimer les backdoors ou accès non autorisés
- [ ] Mettre à jour les dépendances si nécessaire
- [ ] Révoquer et remplacer TOUS les secrets potentiellement exposés

---

### 5. RECOVERY
- [ ] Restaurer depuis une sauvegarde saine si nécessaire
- [ ] Vérifier l'intégrité des données restaurées
- [ ] Remettre le service en ligne progressivement
- [ ] Monitorer intensivement post-restauration
- [ ] Confirmer que la vulnérabilité est corrigée

---

### 6. VERIFICATION
- [ ] L'attaque ne peut plus se reproduire via le même vecteur
- [ ] Les logs ne montrent plus d'activité anormale
- [ ] Les tests de sécurité passent
- [ ] Les services fonctionnent normalement
- [ ] Les utilisateurs affectés ont été notifiés si nécessaire

---

### 7. POST-INCIDENT REVIEW

À faire dans les 72h après résolution :

**Chronologie de l'incident :**
```
[DATE HEURE] — [Événement]
[DATE HEURE] — [Détection]
[DATE HEURE] — [Action prise]
[DATE HEURE] — [Résolution]
```

**Cause racine :**
[Description précise]

**Ce qui a bien fonctionné :**
- [...]

**Ce qui aurait pu être mieux :**
- [...]

**Actions correctives :**
- [ ] [Action 1] — responsable — délai
- [ ] [Action 2] — responsable — délai

**Mise à jour du Threat Model :**
- [ ] Oui → ajouter la menace à THREAT_MODEL.md

---

## 📋 Log de l'incident

| Timestamp | Action | Résultat | Acteur |
|-----------|--------|----------|--------|
| [DATE H] | [Action] | [Résultat] | [Qui] |

---

## 📞 Contacts d'urgence

| Rôle | Nom | Contact |
|------|-----|---------|
| Responsable projet | [Nom] | [Email/Tel] |
| Hébergeur / Cloud | [Provider] | [Support URL] |
| Registrar DNS | [Provider] | [Support URL] |

---

## 🗂️ Incidents passés

| Date | Type | Gravité | Résolution | Durée |
|------|------|---------|------------|-------|
| [DATE] | [Type] | [P1-P4] | [Résumé] | [Xh] |
