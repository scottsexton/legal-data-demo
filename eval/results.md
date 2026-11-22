# Ask evaluation results

Model `databricks-qwen3-next-80b-a3b-instruct`, 20 questions from `eval/questions.jsonl`.

| Metric | Score |
|---|---|
| Expected case retrieved | 19/20 |
| Expected case cited | 19/20 |
| All expected facts in answer | 19/20 |
| Median seconds per answer | 1.8 |

| # | Type | Question | Retrieved | Cited | Facts |
|---|---|---|---|---|---|
| q01 | who | While jailed, who gave police information about a missing woman named Stephanie Kirk, and which murder was he being held for? | ✓ | ✓ | 2/2 |
| q02 | what | What happened at William and Betty Kindle's home on May 13, 2004? | ✓ | ✓ | 2/2 |
| q03 | who | According to Jefferson County, who started the fire at its courthouse, and what was he doing? | ✗ | ✗ | 0/2 |
| q04 | when | When were the Jakubowiczs in a car accident, and who was the other driver? | ✓ | ✓ | 2/2 |
| q05 | when | Who signed the order setting new precinct boundaries for Marion County, and on what date? | ✓ | ✓ | 2/2 |
| q06 | when | When did the Whitestown Town Council introduce its annexation ordinances, and how many were there? | ✓ | ✓ | 2/2 |
| q07 | what | What rate increase did Hamilton Southeastern Utilities ask the regulators for, and when did it file? | ✓ | ✓ | 2/2 |
| q08 | who | Which agency issued a permit to POET Biorefining-North Manchester, and what kind of facility was it for? | ✓ | ✓ | 2/2 |
| q09 | what | How much did Care Group Heart Hospital pay Dr. Sawyer for his redemption? | ✓ | ✓ | 1/1 |
| q10 | what | How did Ashonta Jackson try to distract law enforcement during a bank robbery? | ✓ | ✓ | 1/1 |
| q11 | when | In the Sanchez ethics case, when did Special Agent Coffin get a search warrant, and what did it cover? | ✓ | ✓ | 2/2 |
| q12 | what | What did animal control find at the insured property on July 1, 2009? | ✓ | ✓ | 2/2 |
| q13 | when | Where and when was Paul Michalik found dead? | ✓ | ✓ | 2/2 |
| q14 | what | What mistake did attorney Christopher Hollander make when he texted H.S.? | ✓ | ✓ | 2/2 |
| q15 | who | Who filed to remove Beth Neff from office, and when? | ✓ | ✓ | 2/2 |
| q16 | what | Where did Scott Jones serve notice of the default judgment hearing on Front Row Motors? | ✓ | ✓ | 2/2 |
| q17 | who | Who did Lori Barcroft plan to confront, and why in the early morning? | ✓ | ✓ | 2/2 |
| q18 | who | Which delegate to the 1850 Indiana constitutional convention argued that laws should be general rather than local? | ✓ | ✓ | 1/1 |
| q19 | when | When was Angelo Bobadilla transferred into ICE custody? | ✓ | ✓ | 1/1 |
| q20 | what | What did a juror report on the fifth day of the Ramirez murder trial? | ✓ | ✓ | 1/1 |

## Answers that missed a fact

**q03. According to Jefferson County, who started the fire at its courthouse, and what was he doing?** (expected: Board of Commissioners v. Teton Corp.)

The provided sources do not mention Jefferson County or any fire at a courthouse. Therefore, the question cannot be answered based on the given materials.

