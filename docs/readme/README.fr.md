# Gewu Insight

**Un espace de recherche intégré pour la découverte bibliographique, la lecture, l’organisation des projets et la collaboration avec l’IA.**

Gewu Insight est un espace de travail sur ordinateur pour découvrir, organiser et lire la littérature scientifique. Prépublications, versions publiées, annexes et notes restent rattachées au même article, même lorsqu’il figure dans plusieurs projets. Vous pouvez aussi connecter un assistant IA pour reprendre un travail à partir des sources autorisées et des analyses enregistrées.

[English](../../README.md) · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · **Français** · [Deutsch](README.de.md)

[**Télécharger pour macOS**](https://github.com/LKong92/Gewu-Insight/releases/tag/macos-1.1.0) · [**Télécharger pour Windows**](https://github.com/LKong92/Gewu-Insight/releases/tag/windows-1.1.0) · [**Voir la démonstration**](https://gewu-insight.com/product.html?lang=en#tour) · [Site officiel](https://gewu-insight.com) · [Guides](https://gewu-insight.com/resources.html#resources)

**macOS 1.1.0 · Windows 1.1.0**. Cette présentation est en français ; l’interface et les manuels détaillés sont actuellement en anglais. Les noms des commandes sont conservés tels qu’ils apparaissent dans l’application.

## Découvrir Gewu Insight en vidéo

**[▶ Présentation sur YouTube · anglais · 1:18](https://www.youtube.com/watch?v=8-dK6H2t2gQ)** · [Vidéo sur Bilibili · chinois](https://www.bilibili.com/video/BV1tRxt68E7p/) · [Présentation illustrée sur Zhihu · chinois](https://zhuanlan.zhihu.com/p/2100363950269506568)

Découvrez comment la recherche bibliographique, la lecture, l’organisation des projets, la collaboration avec l’IA et l’intégration Zotero s’articulent dans un même espace de travail.

### Visite détaillée sur le site officiel

<!-- Original video cover: https://gewu-insight.com/assets/product-poster-en.jpg -->
<p align="center">
  <a href="https://gewu-insight.com/product.html?lang=en#tour"><img src="../../assets/readme/product-film-en.jpg" width="720" alt="▶ Voir en anglais · 5:19"></a>
</p>

**[▶ Voir en anglais · 5:19](https://gewu-insight.com/product.html?lang=en#tour)** · **[▶ Voir en chinois · 5:23](https://gewu-insight.com/product.html?lang=zh#tour)**

Cliquez sur la couverture pour regarder sur le site. Les vidéos sont en anglais et en chinois, avec des chapitres consacrés à la découverte, à la bibliothèque, à la lecture, aux publications et à la collaboration avec l’IA.

## Ce que vous pouvez faire

- **Suivre votre domaine** avec Journal, Subject et Author Monitor : revues, thèmes de recherche et auteurs.
- **Réunir les pièces d’un article** dans Paper Files : versions, annexes, annotations et notes, avec un fichier Default de votre choix.
- **Organiser vos projets** dans Library et Spaces, tout en conservant une même fiche pour un article utilisé dans plusieurs contextes.
- **Poursuivre une lecture avec l’IA** à partir des sources et des analyses sauvegardées, selon les droits accordés.
- **Gérer vos publications** dans My Publications : rôles des auteurs, informations de citation et exports.

<details>
<summary>Voir une capture réelle de l’application</summary>

![Capture réelle sous macOS : dossiers de la Library, version publiée et prépublication d’un article, puis informations bibliographiques](../../assets/user-guide/screenshots/library-paper-files.png)

</details>

La [vidéo de présentation de 5 min 19 s](https://gewu-insight.com/product.html?lang=en#tour) montre ces usages en contexte.

## Installer et mettre à jour

| Plateforme | Configuration requise | Téléchargement |
| --- | --- | --- |
| macOS | macOS 14 ou ultérieur ; Apple silicon ou Intel | [DMG 1.1.0](https://github.com/LKong92/Gewu-Insight/releases/tag/macos-1.1.0) |
| Windows | Windows 10 1607 (14393) ou ultérieur, ou Windows 11 ; Intel/AMD x64 | [Setup 1.1.0](https://github.com/LKong92/Gewu-Insight/releases/tag/windows-1.1.0) |

Téléchargez l’installateur dans **Assets** sur la page de la version, et non le ZIP **Source code**. Sur Mac, glissez l’App du DMG vers Applications. Sous Windows, exécutez Setup puis lancez Gewu depuis le menu Démarrer.

Créez ou ouvrez une **Gewu Database**, dans un dossier distinct du programme. Pour conserver une collection Windows existante, choisissez **Use existing Gewu Database**. Python et les dépendances sont inclus ; l’installation éventuelle de WebView2 nécessite Internet. Le paquet Mac n’est pas notarié par Apple et l’installateur Windows n’est pas signé : consultez les [instructions d’installation](https://gewu-insight.com/download.html). LibreOffice et TeX restent facultatifs et s’installent séparément.

Depuis Mac 1.0.x ou Windows 1.0.0, installez manuellement 1.1.0 une fois en conservant la base. Utilisez ensuite **Gewu Insight → Check for Updates** sur Mac ou **Help → Check for Updates** sous Windows. Avant l’installation, sauvegardez vos données, fermez l’onglet Gewu dans Zotero et terminez ou suspendez les imports.

## Essayer avec un article

Glissez un PDF dans Library, ou ouvrez [l’article du projet](https://arxiv.org/abs/2610.14538) dans Browser et choisissez **Save to Gewu**. Si le PDF n’est pas récupéré, téléchargez-le sur arXiv et ajoutez-le à Paper Files dans la même fiche.

1. Rangez l’article dans un dossier de recherche, consultez **Paper Details** et lisez le PDF.
2. Pour utiliser l’IA, suivez le [guide de connexion](../AI_ACCESS.md) : choisissez la collection et les droits de lecture et d’enregistrement nécessaires dans **AI Access**.
3. Remplacez le **Gewu Key** ci-dessous par celui de votre article et demandez au client connecté :

   > Avec les outils MCP de Gewu, lis l’article YOUR_GEWU_KEY et son PDF autorisé. Résume la question, les éléments de preuve et les limites, avec les pages correspondantes. Enregistre l’analyse sur cette fiche via save_analysis, avec l’identifiant et le SHA-256 du fichier source, sans écraser les fichiers existants.

4. Dans une prochaine session autorisée, faites relire la source et l’analyse enregistrée avant de poursuivre les questions ouvertes. La note est consultable dans Paper Files.

La continuité repose sur les documents enregistrés. **Les conversations IA ne sont pas synchronisées automatiquement.** Découverte, organisation et lecture fonctionnent aussi sans compte IA.

## Avec Zotero

Installez le module fourni via **Plugin → Zotero Integration** dans l’App autonome. L’onglet Zotero utilise la même installation de Gewu et la même base sélectionnée, avec les mêmes articles et réglages.

**Save to Gewu** conserve l’article dans Gewu ; **Save to Zotero** copie les métadonnées et, au choix, le PDF Default disponible. **Loader → Import from Zotero** permet de prévisualiser puis de copier la hiérarchie des collections, y compris les collections vides, selon l’organisation des fichiers de Gewu. La base et les originaux Zotero sont préservés. Il ne s’agit pas d’une synchronisation bidirectionnelle continue. [Voir les étapes illustrées](https://gewu-insight.com/zotero.html).

## Données, plateformes et licence

La base, les PDF et les pièces jointes restent en local. La découverte, les sites éditeurs et l’IA en ligne nécessitent une connexion. AI Access est désactivé par défaut ; le client peut transmettre le contenu autorisé à son fournisseur de modèle. Vérifiez les analyses. Les droits MCP ne limitent pas les accès aux fichiers qu’un programme possède indépendamment au niveau du système.

Fermez l’App et son service avant de sauvegarder toute la base, les autres dossiers gérés et les originaux liés à l’extérieur. Copier le programme seul ne sauvegarde pas la recherche. Gewu ne contourne ni les abonnements ni les contrôles d’accès.

macOS est la plateforme principale de développement et de test. Windows 11 a été testé de façon limitée en machine virtuelle ; les correctifs Windows 10 s’appuient surtout sur des retours externes. Les captures et l’évaluation de l’article concernent macOS.

Le code est consultable sous une [licence spécifique de recherche académique et non commerciale](../../LICENSE), qui n’est pas une licence open source. Utilisation, modification et partage sont permis selon ses conditions ; un usage commercial nécessite une autorisation écrite distincte. Les contenus tiers gardent leurs propres conditions.

[Présentation du produit](https://gewu-insight.com/product.html) · [Guides des deux plateformes](https://gewu-insight.com/resources.html#resources) · [IA](https://gewu-insight.com/ai.html) · [Signaler un problème](https://github.com/LKong92/Gewu-Insight/issues)

Le nom chinois, « 格物洞见 », évoque l’étude des phénomènes et la recherche d’explications à travers l’intuition et les représentations physiques. Les questions et le jugement scientifique restent du ressort du chercheur.

Référence : Kong, L. & Wu, Z. *A Stateful Research Information Infrastructure for Scientific Discovery.* arXiv:2610.14538 (2026). [Article](https://arxiv.org/abs/2610.14538) · [BibTeX et éléments de reproductibilité](../../README.md#citation).

Copyright © 2026 Lingyuan Kong and Zhengran Wu.
