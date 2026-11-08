# Rules FAQ check

The official rules FAQ (cyberpunktcg.com/rules-faq, updated 28 Oct 2026) has 311
entries. A raw copy is in `docs/rules-faq.json`.

- **286 card entries.** All of them are already in `data/cards.json` as card rulings,
  and the card scripts were written from them. None are new.
- **25 general entries.** Each one was checked against the engine below. Two didn't
  match and have been fixed, with tests in `tests/test_cards.py`.

| # | Question (short) | FAQ | Engine |
| --- | --- | --- | --- |
| 1 | [ADRENALINE] Unit uses its Spend ability the turn it's played | No | Matches: Adrenaline only lifts lag for attacking |
| 2 | [BLOCKER] the turn it's played | Yes | Matches |
| 3 | A second [BLOCKER] redirects an attack that was already redirected | Yes | Matches |
| 4 | The Unit being attacked uses its own [BLOCKER] | No | Matches (11.28.3.1) |
| 5 | [BLOCKER] when the Gig area is attacked | Yes | Matches |
| 6 | [BLOCKER] when another Unit is attacked | Yes | Matches |
| 7 | A Legend's [BLOCKER] from the Legends area | No | Matches: only Units on the field can block |
| 8 | [GO SOLO] the turn you called the Legend | Yes | Matches |
| 9 | [GO SOLO] with a spent Legend | Yes | Matches: it enters ready |
| 10 | Spend the Legend itself for an Eddie to pay for its own [GO SOLO] | Yes | **Fixed.** The engine used to leave the Legend out of its own payment |
| 11 | Play a Legend without using [GO SOLO] | Yes | **Fixed.** This wasn't possible before (rule 4.5) |
| 12 | A Legend played to the field uses its Spend ability that turn | No | Matches: it has lag |
| 13 | A Legend that went solo is still a Legend | Yes | Matches |
| 14 | [QUICK] during your own turn | Yes | Matches |
| 15 | More than one [QUICK] during a rival's attack | Yes | Matches |
| 16 | [QUICK] lets a Unit use its Spend ability the turn it's played | No | Matches |
| 17 | Respond to a rival's [QUICK] with a [QUICK] | No | Matches: only the defending player reacts |
| 18 | Choose the order of several pending [ATTACK] effects | Yes | Matches (changed earlier from Henry's ruling) |
| 19 | Choose the order of [ATTACK] and "when a friendly Unit attacks" | Yes | Matches |
| 20 | Choose the order of [PLAY] and "when a friendly Legend is spent" | Yes | Matches |
| 21 | [DEFEATED] effect when the defeat is prevented | No | Matches: a prevented defeat triggers nothing |
| 22 | A Unit's Spend ability the turn it's played | No | Matches |
| 23 | A Legend's Spend ability the turn it's called | Yes | Matches: lag only applies on the field |
| 24 | Playing a Legend without [GO SOLO]: lag, same orientation | Yes | **Fixed** with #11: it enters with lag, spent or ready as it was |
| 25 | Adjust a Gig by 0 for "up to X" | Yes, but no "when you adjust" trigger | Matches: choosing not to adjust triggers nothing |
