<!-- Placeholder sample talk. Replace it with your own.
     Marks:  ## Section [m:ss]   [KEY] at line start   /  short pause   //  long pause
             [DEFINE: term]   *word* emphasis (experimental)                              -->
## Introduction [0:40]
Coral reefs cover less than one percent of the ocean floor, / yet they shelter about a quarter of all marine species.
When the water stays too warm for too long, corals expel the algae that feed them. // We call this bleaching.
[DEFINE: bleaching] Bleaching is not death, but a bleached reef is a reef on a clock.
Today I will show that we can predict which reefs will bleach / weeks before it happens, using only satellite data.

## Methods [0:50]
We used twenty years of sea surface temperature records from satellites, covering about four hundred reefs.
For each reef we computed degree heating weeks, [DEFINE: degree heating weeks] which is the accumulated heat stress above the local summer maximum.
We added reef depth and the local tidal range as features.
We trained a gradient boosted model on these features, and we tested it only on reefs it had never seen, / in regions it had never seen.

## Results [0:40]
[KEY] The model predicted bleaching events three weeks in advance, with eighty seven percent accuracy. //
That is two weeks earlier than the warning system reef managers use today.
[KEY] And the errors were not random: / the model struggled most on deep reefs, where the satellite sees the surface but not the coral.
So what does this mean for the people who manage reefs? //
Three weeks is enough time to deploy shading, to pause tourism, / and to collect samples before the damage is done.
[KEY] We cannot stop the ocean from warming this summer. // But we can stop being surprised by it.
Thank you.
