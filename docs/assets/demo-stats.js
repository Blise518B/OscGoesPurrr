/* OscGoesPurrr demo — the Statistics page.
   A model of the app's own page: src/ui/views/statistics.py lays it out,
   src/ui/stats_charts.py paints the charts; this file does both for the web.
   The numbers below are sample data (ten sessions in September 2026),
   computed with the app's own helpers so they add up.

   window.OGPDemoStats.init(rootElement)   build the page inside the fragment
   window.OGPDemoStats.redraw()            repaint the charts (after a colour
                                           change: they read the CSS tokens
                                           when they draw)
   No dependencies, no network. */
(function () {
  'use strict';

  /* Times are local wall-clock seconds written as if they were UTC, so every
     visitor sees the same clock: format with getUTC*(). `lv` is each toy's
     level per 10 s bucket (one base-36 digit, k/35), `thr` thrusts per bucket,
     `zr` the contact runs [from, to) in buckets. */
  var DATA = {"today":[2026,9,26],"now":1790458740,"app_started":1790457240,"lifetime":{"active_s":22322.0,"thrusts":20519,"sessions":10,"toys":{"Lovense Lush":21462.0,"Lovense Edge":9604.0,"Lovense Gush":3470.0},"zones":{"Orf/Pussy":20981.0,"Orf/Mouth":2498.0,"Orf/Anal":3743.0,"Pen/Penis":2134.0}},"facts":{"avg_session_s":2232.2,"avg_session_thrusts":2051.9,"pace":55.1536600663023,"fav_toy":["Lovense Lush",0.6214384989576095],"fav_zone":["Orf/Pussy",0.7147090884316665],"night_share":0.6091300062718394,"busiest_weekday":5,"best_session":[3606,1789165865],"longest_session":[3607.0,1789165865],"record_pace":[120,1789165865]},"hours":{"2026-09-05T21":[673.0,480],"2026-09-05T22":[2272.0,2461],"2026-09-06T19":[1462.0,1010],"2026-09-11T22":[1274.0,1121],"2026-09-11T23":[2333.0,2485],"2026-09-12T23":[1337.0,1192],"2026-09-13T00":[1307.0,1141],"2026-09-15T20":[1322.0,1189],"2026-09-17T22":[438.0,413],"2026-09-17T23":[1321.0,1314],"2026-09-19T20":[940.0,706],"2026-09-19T21":[2454.0,2191],"2026-09-20T16":[860.0,811],"2026-09-23T21":[1014.0,802],"2026-09-23T22":[861.0,1046],"2026-09-25T22":[1778.0,1501],"2026-09-25T23":[676.0,656]},"sessions":[{"id":"20260925-221503","start":1790374503,"duration_s":4056.0,"active_s":2454.0,"thrusts":2157,"peak_pace":101,"spark":[0.63,0.61,0.93,0.6,0.45,1.0,0.6,0.83,0.65,0.99,0.89,0.93,0.6,0.0,0.0,0.39,0.66,0.73,0.79,0.91,0.91,0.94,0.8,0.79,0.9,0.93,0.86,0.97,0.96,0.91,0.71,0.53,0.93,0.42,0.0,0.0,0.41,0.34,0.67,0.96,0.53,0.55,0.93,0.57,0.63,0.79,0.87,0.9],"toys":{"Lovense Lush":2454.0,"Lovense Edge":1073.0},"zones":{"Orf/Pussy":2397.0,"Orf/Mouth":550.0,"Orf/Anal":530.0},"bucket_s":10,"start_i":27,"n":359,"lv":{"Lovense Lush":"29aceb56522225278a88485222233329b00b0immnknlmmlkf0008989b34456586nsuonqqrrrtolqrrosrxupkhhha9b00000000000000000000006445768c67639856678cf7b9bb57dabgfedfgfccmidgifceknmgfh5656qmpnrqkkldc8aabgcfikgljjgigfbddaggf9ebidfijjmooln8787onlinl000mmosotvpromjii000000000000000000000889c69e000a8a9bfc344egdagjlnk000lmkjmo79889vkgkkig344jfc343bd8d000ehijhffghiklnoswxosqni","Lovense Edge":"00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000ermemneaahkjaag8b7culrptsijiec8978fcilnjqnojmjfa995ccf7dcmejnlmoqogj9554jllhpj000m000000000000000000000000000000000000000000000000000000000000hjg000ijllmo7haadskbghgf186mig87dgh9g0008fgggggfimomor00000000"},"thr":"0000000000003334454535330000000470060bbedbdccceb90007645800000000dhieggefiehacffgdfhlica7bb76800000000000000000000000000000000000000000000000034787a98788a77ba99b768bcea980000fefdfeca9965766865ca6cb77ba75896aa75a799baadceddb0000cae8d9000dd9hagieef9acc000000000000000000000000000000000007970009a977bdfd000cbcbaa00000kd7c8b900096900069470009bac689686eadgihjcihb7","zr":{"Orf/Pussy":[[0,33],[35,49],[52,94],[116,233],[236,250],[271,278],[281,300],[303,334],[337,359]],"Orf/Mouth":[[24,33],[37,49],[173,212],[297,300],[303,317]],"Orf/Anal":[[32,33],[35,45],[47,49],[186,228],[315,334]]},"an":{"window_start_s":270,"window_s":3590,"peak_pace":101,"peak_pace_at_s":3780,"hot_kind":"thrusts","hot_value":396,"hot_at_s":910,"hot_len_s":300,"streak_s":1340,"streak_at_s":1430,"break_s":220,"break_at_s":1210,"top_toy":"Lovense Lush","top_toy_share":0.6958,"top_toy_level":0.5094,"top_zone":"Orf/Pussy","top_zone_s":2397.0}},{"id":"20260923-212826","start":1790198906,"duration_s":3168.0,"active_s":1875.0,"thrusts":1848,"peak_pace":119,"spark":[0.4,0.74,0.83,0.96,0.87,0.94,0.97,0.56,0.68,0.52,0.68,0.72,0.87,0.48,0.9,0.2,0.0,0.0,0.0,0.1,0.67,0.26,0.58,0.92,0.92,0.95,0.92,0.97,0.76,0.35,0.98,0.9,0.82,0.97,0.84,0.85,0.9,0.98,0.94,0.95,0.94,0.85,0.42,0.83,0.94,0.82,0.4,0.97],"toys":{"Lovense Lush":1875.0,"Lovense Edge":1012.0},"zones":{"Orf/Pussy":1828.0,"Orf/Mouth":444.0},"bucket_s":10,"start_i":30,"n":263,"lv":{"Lovense Lush":"766658623349555addkdhgmoqmklgonghimfhhnmk237da3354g3566ikki00heeknkjlmoo8675knmmhed00000000000000000000000006576999680007a8addbgcifddbceibcfidechgnlihklijhf4344500imnqnphkoolinnnmlknnmpa79cggjdhkoiegd9cdedfgffidinihjkdinokoollnpr888979asutyxwzzzooowvss97977qsmrsj","Lovense Edge":"000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000099000366affemepkfhdfei68egbb9kgppojqqhjfb2312300gmnsrtjmopkdighgghjiinccdhkgmcijlfafd5aghfjmmjnfjnddhi8dkmimnlmmsugdca7a9qlj000000000000000000000000"},"thr":"000000000000002777c8a98df8b98fea8be899a99007860000a00009bdc00978db9bbebd00009cdea6800000000000000000000000000000000000000000096989a9864aa757b98798fcb8bbaca80000000beegfd7caddaa9c9bcdedd74568898a7cba6a68798a88aa88fc8cb8cdcccebdfbd0000000gfhjijlkmeedihfe00000egdfgb","zr":{"Orf/Pussy":[[0,59],[61,83],[108,117],[120,161],[163,263]],"Orf/Mouth":[[40,59],[136,161],[163,185]]},"an":{"window_start_s":300,"window_s":2630,"peak_pace":119,"peak_pace_at_s":2690,"hot_kind":"thrusts","hot_value":361,"hot_at_s":2520,"hot_len_s":300,"streak_s":1550,"streak_at_s":1380,"break_s":250,"break_at_s":1130,"top_toy":"Lovense Lush","top_toy_share":0.6495,"top_toy_level":0.5624,"top_zone":"Orf/Pussy","top_zone_s":1828.0}},{"id":"20260920-161209","start":1789920729,"duration_s":1352.0,"active_s":860.0,"thrusts":811,"peak_pace":101,"spark":[0.55,0.65,0.85,0.65,0.55,0.95,0.67,1.0,0.7,0.95,0.8,0.95,0.9,0.93,1.0,0.95,0.95,0.95,1.0,1.0,0.9,0.95,0.9,0.95,0.55,1.0,0.75,0.57,0.35,0.45,1.0,0.85,0.9,0.85,0.87,0.9,0.8,0.9,0.85,0.35,1.0,0.9,1.0,1.0,1.0,0.95,0.85,0.87],"toys":{"Lovense Edge":860.0},"zones":{"Orf/Anal":833.0},"bucket_s":10,"start_i":15,"n":103,"lv":{"Lovense Edge":"24459ab6743856998b97ab9bcehihindflmhhfhhiffihdbffgi54hhd54443432deijjkklloosqovsyvs0orqstqnovwpuokkeha8"},"thr":"00000000000000056444555698ab9cd99bb9c8bbba89a76999a009980000000099a9aa9bbadedchgkjh0bfgcggefihghd99a764","zr":{"Orf/Anal":[[0,103]]},"an":{"window_start_s":150,"window_s":1030,"peak_pace":101,"peak_pace_at_s":920,"hot_kind":"thrusts","hot_value":407,"hot_at_s":820,"hot_len_s":300,"streak_s":1030,"streak_at_s":150,"break_s":0,"break_at_s":150,"top_toy":"Lovense Edge","top_toy_share":1.0,"top_toy_level":0.5276,"top_zone":"Orf/Anal","top_zone_s":833.0}},{"id":"20260919-203647","start":1789850207,"duration_s":4884.0,"active_s":3394.0,"thrusts":2897,"peak_pace":107,"spark":[0.52,0.69,0.92,0.72,0.97,0.6,0.93,0.93,0.8,0.64,0.92,0.69,0.64,0.0,0.04,0.7,0.55,0.78,0.94,0.93,0.88,0.94,0.84,0.71,0.94,0.82,0.99,0.73,0.9,0.93,0.93,0.86,0.67,0.72,0.77,0.0,0.46,0.68,0.71,0.85,0.88,0.76,0.79,0.8,0.82,0.71,0.86,0.93],"toys":{"Lovense Lush":3394.0,"Lovense Gush":2331.0,"Lovense Edge":2041.0},"zones":{"Orf/Pussy":3309.0,"Orf/Anal":806.0,"Orf/Mouth":654.0,"Pen/Penis":712.0},"bucket_s":10,"start_i":20,"n":455,"lv":{"Lovense Lush":"48b980979754374a337742283885b333c9eba8cb6c69ac6b6266700086eb5egignoiolknknnmlmjnlfde54566igdfkijmmrosmmosyoqn887775fhf9d70000000000000000000069adbaa7eba7643233777643257aa6adc574246599aa9dajdljnligekopjoqocd988a4b6aacd43354kloihihmmooopmikknjlmi0lgmigjkmpskk00tmksqou7a7875d9ec8ageb8cfg9acgfglgdhlnlsonoqomll877787aavotstqkjfehecb000000000000000989dbffh99fagejknhl677rtsuqoqljoorsvoedebcb8c00fgaaciiflllmpo77887vwuusvuye8587f4439dgj645iigilhijlmkmnjjehefa6","Lovense Gush":"000000000005183b1376656g9ge8g463d8d989ce9iaehkah8386700085he8kkojrrhmjfichieglhoohhi7a978gb8bgdelmsnvnlorwolh7866500000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000006b1a389bf787aepoqihgbheifjnnhlkrnori0mfjc9ceejqgi00vmkvoos6b6443d7hdadnigdhhj76bebdjdajoqkvnmpsomjf64449700000000000000000000000000000000000000000000000000007pqlniikednomntoifkhhe8b00cf9aailgpqoosodcb97polpqooxkdafdl9b87bde858ijijnilm0000000000000","Lovense Edge":"00000000000000000000000000000003d8d989ce9iaehkah8386700085he8kkojrrhmjfichieglhoohhi7a978gb8bgdelmsnvnlorwolh7000000000000000000000000000000000000000000000000000000000000000000000000000eg8i8hfjhgeempskssnii976b1a389bf787aepoqihgbheifjnnhlkrnori0mfjc9ceejqgi00vmkvoos6b6443d7hdadnigdhhj76bebdjd000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000khhe8b00cf9aailgpqoosodcb97polpqooxkdafdl9b87bde858ijij00000000000000000"},"thr":"000000000000000000043135454250008577577659546635323350004268487b9eddeeada8d9dbcbb76a0000097988abcdfdidbbgldgf000000bb66530000000000000000000000000000000000000000000000456667634422465743775a9caaab989ebcaef886758265577a00000abd8a9accgffe99bdbc9cb0b9db8cbdfhac00hbbgccf576653a58735887778b6779aac96a8aahbdeebcad00000000gfgeig8b78a8780000000000000000000000000000000aab000ffehc9h8baahika8585775700ab657bc8ccaaga00000hihjgiij64343700046aa0009b78b7b9dbaefc9599764","zr":{"Orf/Pussy":[[0,53],[56,121],[141,257],[259,329],[344,389],[391,455]],"Orf/Anal":[[12,20],[22,39],[41,44],[172,185],[188,243],[355,373],[375,389],[391,393]],"Orf/Mouth":[[44,53],[56,72],[74,87],[177,210],[387,389],[391,411]],"Pen/Penis":[[56,95],[200,248],[406,426]]},"an":{"window_start_s":200,"window_s":4550,"peak_pace":107,"peak_pace_at_s":4320,"hot_kind":"thrusts","hot_value":342,"hot_at_s":2470,"hot_len_s":300,"streak_s":1880,"streak_at_s":1610,"break_s":200,"break_at_s":1410,"top_toy":"Lovense Lush","top_toy_share":0.437,"top_toy_level":0.5011,"top_zone":"Orf/Pussy","top_zone_s":3309.0}},{"id":"20260917-224833","start":1789685313,"duration_s":2712.0,"active_s":1759.0,"thrusts":1727,"peak_pace":107,"spark":[0.66,0.74,0.92,0.94,0.86,0.7,0.86,0.94,0.98,0.96,0.92,0.98,0.58,0.74,0.3,0.93,0.88,0.92,0.88,0.48,0.98,0.56,0.0,0.0,0.0,0.0,0.0,0.34,0.76,0.72,0.82,0.93,0.76,0.9,0.6,0.9,0.94,0.96,0.86,0.92,0.94,0.64,0.36,0.68,0.96,0.92,1.0,0.98],"toys":{"Lovense Lush":1759.0,"Lovense Edge":605.0},"zones":{"Orf/Pussy":1736.0,"Orf/Anal":154.0},"bucket_s":10,"start_i":18,"n":243,"lv":{"Lovense Lush":"55452894689b79dcfdiiefijf666nklkclpkqorpoqvuttpqnokokoefb9fggi00b7da34340348bb77a8fhhggnloosvsrno7687spopoicd00000000000000000000000000000088b567839dbb69b6degba9efcdh0hllh5555kjkjjmonnrststpq9babfgdffkjfdhfnijm575554565fijpmnptuxuotsuvxtsustmh","Lovense Edge":"000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000a28c5ggjefgmmehj0gjhc2277lmonkosmorommnii477bfhegimnfdgblbfj4766779abgjjrmk000000000000000000"},"thr":"000000000000389878aa789a9000bd9c6bbcfchgfhifgideccccac78948b8a0084740000000568564486b9aeefdihfdab0000egdgg969000000000000000000000000000000000000000000000678a875999790abb900009cabb9debghifhgf6847786a8db87a8e9be0000000006c8ebbfhgjgchghjjigieicc","zr":{"Orf/Pussy":[[0,62],[64,109],[139,243]],"Orf/Anal":[[150,174]]},"an":{"window_start_s":180,"window_s":2430,"peak_pace":107,"peak_pace_at_s":2510,"hot_kind":"thrusts","hot_value":369,"hot_at_s":460,"hot_len_s":300,"streak_s":1090,"streak_at_s":180,"break_s":300,"break_at_s":1270,"top_toy":"Lovense Lush","top_toy_share":0.7441,"top_toy_level":0.5508,"top_zone":"Orf/Pussy","top_zone_s":1736.0}},{"id":"20260915-200518","start":1789502718,"duration_s":1994.0,"active_s":1322.0,"thrusts":1189,"peak_pace":99,"spark":[0.53,0.7,0.65,0.53,0.7,0.57,0.85,0.93,0.82,0.63,0.38,0.6,0.93,0.88,0.93,0.97,0.4,0.53,0.87,0.97,0.97,0.95,1.0,0.93,1.0,0.9,0.85,0.97,0.82,0.9,0.33,1.0,0.78,0.8,0.97,0.0,0.9,0.88,0.93,0.42,0.93,0.93,1.0,0.93,1.0,0.93,1.0,0.9],"toys":{"Lovense Lush":1322.0},"zones":{"Orf/Pussy":1305.0},"bucket_s":10,"start_i":14,"n":166,"lv":{"Lovense Lush":"9a97be8acc79da79aa7d8bb98ca67c5c233334222afefdhhijilkqlo77776oononoppploprpqstvrnsp9chddgijg8699487ca752333bddddedaafafdc000bhfgegeaggd00lnmpmkmmmnkrqtorooqmlmmhhnoke"},"thr":"000000000000000000004567574247480000000006888998bbaeaed900000eeabcdgdgcecgdghijdeid87976ca9955761549642000077a5667559599800059886887967009ddb8dfddccfhfafcddebcccaacb8","zr":{"Orf/Pussy":[[0,121],[124,135],[137,166]]},"an":{"window_start_s":140,"window_s":1660,"peak_pace":99,"peak_pace_at_s":870,"hot_kind":"thrusts","hot_value":382,"hot_at_s":750,"hot_len_s":300,"streak_s":1660,"streak_at_s":140,"break_s":0,"break_at_s":140,"top_toy":"Lovense Lush","top_toy_share":1.0,"top_toy_level":0.5193,"top_zone":"Orf/Pussy","top_zone_s":1305.0}},{"id":"20260912-232552","start":1789255552,"duration_s":3747.0,"active_s":2644.0,"thrusts":2333,"peak_pace":89,"spark":[0.7,0.7,0.51,0.43,0.76,0.67,0.89,0.74,0.73,0.9,0.96,0.97,0.93,0.96,0.91,0.99,0.99,0.93,0.96,0.83,0.99,0.97,0.8,0.0,0.0,0.53,0.4,0.64,0.86,0.79,0.97,0.64,0.9,0.9,0.79,0.69,0.9,0.96,0.94,0.97,0.46,0.94,0.87,0.93,0.79,0.94,0.9,0.97],"toys":{"Lovense Lush":2644.0,"Lovense Gush":1139.0},"zones":{"Orf/Pussy":2582.0,"Pen/Penis":552.0},"bucket_s":10,"start_i":30,"n":334,"lv":{"Lovense Lush":"38452226aagcae858c899f900afdfkko56576eggkmjgkhiig56id9ehfeb08gaa56a899aaedcfhcdejkeijfccccedejklnlmokikolkokmqmlmnjfilmhgiklgmikkmlqnss88ppopnkjkmqqqmmeghcb26900000000000000004526422000232222223366422224658234aabikhkjk777jkonokmigjmnroplpoqqv7a9s0ptoosqn5462768388244258cfdeiecege65545eifklihkefhklmllmlkkimk0ilkonmkppqppsrtqqonnef957","Lovense Gush":"000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000bea8675496a134bbaknlqlka78ffjggcjfdgjktosntoolr7b7i0hnojssobcf7b8a2a9113147chfhkhgihda55238fbkkijohhikokkkjhhigkk0inorpnlsookllijijijo00000"},"thr":"00000000000000000000000000009abb00000888aab7c9a9900b767a75604765343456767769c679baaba8876888adadeebfb7ddbcfbefcdedcabcc8bbac7bacbbcgddh00geedccaadgfcce8aa8724500000000000000000000000000000000000000000000034233759bd99b8000cafbdbd96cbefbe9fbghi000h0gibdhed24614432453332247a79b698a6000009a8dc899788d8cabeadcadb08cbdc9bfdeeehcibfccf78556","zr":{"Orf/Pussy":[[0,23],[25,159],[175,182],[185,334]],"Pen/Penis":[[35,79],[226,236],[238,266]]},"an":{"window_start_s":300,"window_s":3340,"peak_pace":89,"peak_pace_at_s":2770,"hot_kind":"thrusts","hot_value":362,"hot_at_s":3290,"hot_len_s":300,"streak_s":1590,"streak_at_s":300,"break_s":160,"break_at_s":1890,"top_toy":"Lovense Lush","top_toy_share":0.6989,"top_toy_level":0.4962,"top_zone":"Orf/Pussy","top_zone_s":2582.0}},{"id":"20260911-223105","start":1789165865,"duration_s":5297.0,"active_s":3607.0,"thrusts":3606,"peak_pace":120,"spark":[0.58,0.63,0.63,0.98,0.94,0.59,0.94,0.97,0.91,0.96,0.95,0.82,0.85,0.67,0.66,0.43,0.0,0.0,0.53,0.66,0.85,0.77,0.81,0.83,0.66,0.98,0.95,0.69,0.94,0.77,0.88,0.0,0.0,0.49,0.58,0.93,0.58,0.81,0.78,0.95,0.96,0.87,0.95,0.68,0.95,0.69,1.0,0.67],"toys":{"Lovense Lush":3607.0,"Lovense Edge":1559.0},"zones":{"Orf/Pussy":3537.0,"Pen/Penis":870.0,"Orf/Anal":734.0},"bucket_s":10,"start_i":16,"n":499,"lv":{"Lovense Lush":"2267572422624767666ab9aghddddachfikfihhjefhegecdb87ccc000f44ehdeddbdjjkmnnptsvtslnnekmjffidbbdcaeb97bfeigdiinmokdhmlkjojjn6555kjmjijjjjl000nstpornlk67565gdcd6840000000000000000000000000000bbbahegfacedeejhaggie7bdecc9bcbdffd84232c7bbec7ca3322eicfagefbcfhmq000tsuwsostwprttosrloqnmh5500nqmjiknorostvvyzyzvobbcdzyyvsovzpnjea600000000000000000000000657665562535422688bca758cdgddc6333200eehilhcdkjff0ggcciek565jioikmrtsoxqqtzxxibggmnhhfadbgekehhopkfkmno66789utvvvxvvwszxvtormo77777nqvtyzwttzyyvts000kligi","Lovense Edge":"0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000cgdhf6b95111eibjbkjjghkjmp000nmnsnkstypputoqqhilijd5400msoljoqpqojlsqptpuvohfglvvtrsopqgg0000000000000000000000000000000000000000000000000000000000000000000000000000000ccliqbaajipegfklnnsmmqzywnekinmcdc7a6fdlegisslglnmj54757mluvvvtvxsztupiofh59a77nqxqzztopvpqoil00000000"},"thr":"0000000000000000000000000000009aaad8998c97988867875566000900aa887878b8aedefhfhggdcf89fba888788876686997888bcdccd9adbc9gcca0000b8cbbcba8d000ehgedfadd00000a6594450000000000000000000000000000000000000000000000000000086458766a75400085689649600009a786858889aad000iihiggffiefhgcifcffdcb0000def8adceecifijlmjkje0000mliigfikceb963000000000000000000000000000000000000000005953476787684000000588c86977ab809896b59000caea9egifckefgljjb5a7af9785777aa7baefb8db9d00000hikkhijikemlijghfd00000dcgglmkgglljgfh000ac98a","zr":{"Orf/Pussy":[[0,54],[57,136],[139,160],[188,255],[258,282],[284,322],[345,380],[382,491],[494,499]],"Pen/Penis":[[25,53],[57,75],[237,255],[258,268],[270,275],[383,393],[395,396],[398,429]],"Orf/Anal":[[63,68],[71,92],[210,243],[373,380],[382,421]]},"an":{"window_start_s":160,"window_s":4990,"peak_pace":120,"peak_pace_at_s":3130,"hot_kind":"thrusts","hot_value":443,"hot_at_s":4740,"hot_len_s":300,"streak_s":1600,"streak_at_s":160,"break_s":280,"break_at_s":1760,"top_toy":"Lovense Lush","top_toy_share":0.6982,"top_toy_level":0.5694,"top_zone":"Orf/Pussy","top_zone_s":3537.0}},{"id":"20260906-191040","start":1788721840,"duration_s":2284.0,"active_s":1462.0,"thrusts":1010,"peak_pace":70,"spark":[0.65,0.75,0.5,0.38,0.97,0.93,0.95,0.93,0.68,0.57,0.95,0.93,0.97,0.9,0.97,0.93,0.93,1.0,0.93,0.68,0.82,0.93,0.85,0.97,0.95,0.42,0.0,0.15,0.45,0.65,0.6,0.88,0.93,0.65,1.0,0.82,0.45,0.8,0.95,0.9,0.62,0.55,0.82,0.97,0.35,0.75,0.88,0.95],"toys":{"Lovense Lush":1462.0},"zones":{"Orf/Pussy":1444.0,"Orf/Mouth":331.0},"bucket_s":10,"start_i":27,"n":192,"lv":{"Lovense Lush":"42222232222563006522259789babcbfgi22229bcgjeefeaa98dbfkljmigedchfihkaadhaccbad453elhgmhheclikjmnfgfbd40000000003477834379d997ccda6a6224a989ehjqo77876jm44356aa78d703556kemjjbggd05567lpopmnieha9"},"thr":"000000000000000043241543457576878900003588a977a5755866aaacc898766b8b678c48887a0009db9cbc75e899dd7aa675000000000000000000000648865545004566589dec00000aa444527724a500000d8b9c69a800000ee9f8aba766","zr":{"Orf/Pussy":[[0,14],[16,102],[111,192]],"Orf/Mouth":[[59,67],[69,99],[156,168]]},"an":{"window_start_s":270,"window_s":1920,"peak_pace":70,"peak_pace_at_s":2080,"hot_kind":"thrusts","hot_value":254,"hot_at_s":960,"hot_len_s":300,"streak_s":1020,"streak_at_s":270,"break_s":90,"break_at_s":1290,"top_toy":"Lovense Lush","top_toy_share":1.0,"top_toy_level":0.3877,"top_zone":"Orf/Pussy","top_zone_s":1444.0}},{"id":"20260905-214211","start":1788644531,"duration_s":4465.0,"active_s":2945.0,"thrusts":2941,"peak_pace":115,"spark":[0.56,0.64,0.67,0.95,0.78,0.94,0.86,0.95,0.69,0.98,0.26,0.91,0.72,0.91,0.12,0.0,0.33,0.79,0.74,0.94,0.72,0.26,0.89,0.84,0.89,0.94,0.9,0.86,0.93,0.77,0.12,0.0,0.57,0.69,0.77,0.59,0.84,0.75,0.93,0.94,0.95,0.86,0.86,0.49,0.94,0.96,0.95,0.91],"toys":{"Lovense Lush":2945.0,"Lovense Edge":2454.0},"zones":{"Orf/Pussy":2843.0,"Orf/Mouth":519.0,"Orf/Anal":686.0},"bucket_s":10,"start_i":23,"n":405,"lv":{"Lovense Lush":"4222765653552069898bdh000fghcjcfga9aec7353b47654bggeijkfjikghgibbdhiecj434fkhigbgffd66656000mjormrssobaasyzysssstqlokjh00000000000000000000ac77633888adafdd8eecdbea9789abbcdgea00f3000343ec9ehegfdhn0nqpoorqlnnrowvzzxqtuuvqvqusysuxqposrovoxyvovyrqaaayssnqpl000000000000000009a63228abha9bc65252a77a2000eijfdhffiggb54456mkmoollnlmprprmnnjimnqr7de99bafbedcefjjmklhjciik0000cdbdekgfglilrpmnkmkrprrrnqrqutusyotqmh","Lovense Edge":"0000000fd88a10694769fm000hljdl9ge866bb65c9iahgb7fhfbdei9dhkeginfgfjmg9g212cheigbjhjheac67000geknfoqpojaasxwurmjljj000000000000000000000000000000000000bafdb7ihekgmhfa897699cefa00k7000795hd8becde9fo0qtrposqijikooktsslqvsvovnsstmnqgggsontoxztovxonda8skne000000000000000000000000000000000e997a8iedf9000begc9hggnlngd9787kiiijfilikpsstmnmggihhi3cd7adekekihkjlgidhbh7ghj0000hihheldccfbdmmi00000000000000000000000"},"thr":"000000000000406766687b000aab7b887646a8300073652257c8ab8786aa99a6787b88b0009b9ba6989700000000d9decefge000ikjkfehfhbbbc9c00000000000000000000000000000000000000059776546656877b7700a0000000775776888ad0ecfafedbdbhclglllfgggiciefelefjfd9fibhdjkhegldh000jdfdedd000000000000000000000000000000000000000700009c878b79a8a700000dcdfgb9cdadcghaaecbbfhg589785474987969beccc8497a000067568bb89aaafedbbccgbhdfegidghgelbgfc8","zr":{"Orf/Pussy":[[0,22],[25,89],[92,119],[139,175],[177,179],[182,254],[271,295],[298,363],[367,405]],"Orf/Mouth":[[12,22],[27,38],[195,230],[346,363]],"Orf/Anal":[[63,73],[75,89],[92,101],[165,175],[177,179],[182,195],[302,307],[309,341]]},"an":{"window_start_s":230,"window_s":4050,"peak_pace":115,"peak_pace_at_s":2320,"hot_kind":"thrusts","hot_value":490,"hot_at_s":2320,"hot_len_s":300,"streak_s":1190,"streak_at_s":230,"break_s":200,"break_at_s":1420,"top_toy":"Lovense Lush","top_toy_share":0.5455,"top_toy_level":0.5646,"top_zone":"Orf/Pussy","top_zone_s":2843.0}}]};

  var WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  var WEEKDAYS_LONG = ['Mondays', 'Tuesdays', 'Wednesdays', 'Thursdays', 'Fridays', 'Saturdays', 'Sundays'];
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
    'September', 'October', 'November', 'December'];
  var ZONE_TYPES = { Orf: 'socket', Pen: 'plug', Touch: 'touch' };
  var TOY_HUES = ['cyan', 'blue', 'purple'];          /* theme.TOY_HUES */
  var SPANS = [[28, 'over the last 4 weeks'], [91, 'over the last 3 months'], [null, 'all time']];
  var TOKENS = ['card', 'well', 'accent', 'ink', 'txt', 'muted', 'dim',
    'green', 'green-mid', 'green-tint', 'cyan', 'blue', 'purple', 'pink', 'amber'];

  var S = {
    root: null, el: {}, span: 1, month: null, detail: null, listScroll: 0,
    colors: null, family: '"Segoe UI", sans-serif', hoverCol: null, tipTimer: 0,
    sparks: [], tl: null
  };

  /* ── formatting (stats_charts.fmt_*) ──────────────────────────────────── */

  function r0(x) {                       /* Python's round(): half to even */
    var f = Math.floor(x), d = x - f;
    if (d > 0.5) return f + 1;
    if (d < 0.5) return f;
    return f % 2 === 0 ? f : f + 1;
  }
  function p2(n) { return (n < 10 ? '0' : '') + n; }
  function num(n) { return String(Math.trunc(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ','); }
  function pct(x) { return r0(x * 100) + '%'; }
  function fmtDur(sec) {
    var s = Math.max(0, r0(sec || 0));
    if (s < 60) return s + 's';
    var m = Math.floor(s / 60); s %= 60;
    if (m < 60) return m + 'm ' + p2(s) + 's';
    var h = Math.floor(m / 60); m %= 60;
    if (h < 24) return h + 'h ' + p2(m) + 'm';
    return Math.floor(h / 24) + 'd ' + (h % 24) + 'h ' + p2(m) + 'm';
  }
  function fmtShort(sec) {
    var s = Math.max(0, r0(sec || 0));
    if (s < 60) return s + 's';
    var m = Math.floor(s / 60);
    if (m < 60) return m + 'm';
    var h = Math.floor(m / 60); m %= 60;
    if (h < 24) return h + 'h ' + p2(m) + 'm';
    return Math.floor(h / 24) + 'd ' + (h % 24) + 'h ' + p2(m) + 'm';
  }
  function dt(wall) { return new Date(wall * 1000); }
  function clock(wall) { var d = dt(wall); return p2(d.getUTCHours()) + ':' + p2(d.getUTCMinutes()); }
  function weekday(d) { return (d.getUTCDay() + 6) % 7; }           /* Monday = 0 */
  function day(wall) {
    var d = dt(wall);
    return WEEKDAYS[weekday(d)] + ' ' + d.getUTCDate() + ' ' + MONTHS[d.getUTCMonth()];
  }
  function hourKey(wall) {
    var d = dt(wall);
    return d.getUTCFullYear() + '-' + p2(d.getUTCMonth() + 1) + '-' + p2(d.getUTCDate()) + 'T' + p2(d.getUTCHours());
  }
  function zoneLabel(key) {
    var i = key.indexOf('/');
    if (i < 0 || i === key.length - 1) return key;
    var type = key.slice(0, i);
    return key.slice(i + 1) + ' (' + (ZONE_TYPES[type] || type) + ')';
  }
  function byName(a, b) { a = a.toLowerCase(); b = b.toLowerCase(); return a < b ? -1 : a > b ? 1 : 0; }
  function byAmount(map) {                /* most first, then by name */
    return Object.keys(map).sort(function (a, b) { return (map[b] - map[a]) || byName(a, b); });
  }

  /* ── the read model (stats_history.weekday_hour / month_days) ─────────── */

  function weekdayHour(days) {
    var since = days ? hourKey(DATA.now - days * 86400) : null;
    var active = [], thrusts = [], d, key;
    for (d = 0; d < 7; d++) { active.push(new Array(24).fill(0)); thrusts.push(new Array(24).fill(0)); }
    for (key in DATA.hours) {
      if (since !== null && key < since) continue;
      var wd = weekday(new Date(Date.UTC(+key.slice(0, 4), +key.slice(5, 7) - 1, +key.slice(8, 10))));
      var hour = +key.slice(11, 13);
      active[wd][hour] += DATA.hours[key][0];
      thrusts[wd][hour] += DATA.hours[key][1];
    }
    return { active: active, thrusts: thrusts };
  }
  function monthDays(year, month) {
    var days = {}, prefix = year + '-' + p2(month) + '-', key;
    function get(d) { return days[d] || (days[d] = { active_s: 0, thrusts: 0, sessions: 0 }); }
    for (key in DATA.hours) {
      if (key.indexOf(prefix) !== 0) continue;
      var e = get(+key.slice(8, 10));
      e.active_s += DATA.hours[key][0];
      e.thrusts += DATA.hours[key][1];
    }
    DATA.sessions.forEach(function (s) {
      var d = dt(s.start);
      if (d.getUTCFullYear() === year && d.getUTCMonth() + 1 === month) get(d.getUTCDate()).sessions += 1;
    });
    return days;
  }
  function daysIn(year, month) { return new Date(Date.UTC(year, month, 0)).getUTCDate(); }
  function sessionById(id) {
    for (var i = 0; i < DATA.sessions.length; i++) if (DATA.sessions[i].id === id) return DATA.sessions[i];
    return null;
  }
  function decode(str) {                  /* base-36 digits -> numbers */
    var out = new Array(str.length);
    for (var i = 0; i < str.length; i++) out[i] = parseInt(str.charAt(i), 36);
    return out;
  }

  /* ── colours: the CSS tokens, read when a chart draws ─────────────────── */

  function parseColor(str) {
    var m = /rgba?\(([^)]+)\)/.exec(str);
    if (m) {
      var p = m[1].split(/[\s,\/]+/).filter(Boolean).map(parseFloat);
      return [p[0], p[1], p[2]];
    }
    m = /color\(srgb\s+([^)]+)\)/.exec(str);          /* color-mix() results */
    if (m) {
      var q = m[1].split(/[\s\/]+/).filter(Boolean).map(parseFloat);
      return [Math.round(q[0] * 255), Math.round(q[1] * 255), Math.round(q[2] * 255)];
    }
    return [128, 128, 128];
  }
  function colors() {
    if (S.colors) return S.colors;
    var probe = S.el.probe, out = {};
    TOKENS.forEach(function (name) {
      probe.style.color = 'var(--' + name + ')';
      out[name] = parseColor(getComputedStyle(probe).color);
    });
    S.family = getComputedStyle(S.root).fontFamily || S.family;
    S.colors = out;
    return out;
  }
  function css(c, alpha) {
    return alpha == null ? 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')'
      : 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + alpha + ')';
  }
  function blend(a, b, t) {
    t = Math.max(0, Math.min(1, t));
    return [Math.round(a[0] + (b[0] - a[0]) * t), Math.round(a[1] + (b[1] - a[1]) * t),
      Math.round(a[2] + (b[2] - a[2]) * t)];
  }
  /* Active time: nothing = the well, then the green tint up to the vibrant. */
  function ramp(C, t) {
    if (t <= 0) return C.well;
    return blend(C['green-tint'], C.green, 0.22 + 0.78 * Math.min(1, t));
  }
  function toyColor(C, i) { return C[TOY_HUES[i % TOY_HUES.length]]; }
  function zoneColor(C, key) { return key.indexOf('Touch/') === 0 ? C.amber : C.pink; }

  /* ── canvas helpers ───────────────────────────────────────────────────── */

  /* Size the backing store to the pixels the canvas really covers (device
     pixel ratio x the CSS scale of the app window) and draw in CSS pixels. */
  function prep(canvas, height) {
    var w = canvas.clientWidth;
    if (!w) return null;                                /* page not shown yet */
    var h = height || canvas.clientHeight;
    var rect = canvas.getBoundingClientRect();
    var scale = rect.width > 0 ? rect.width / w : 1;
    var ratio = Math.max(0.5, Math.min(4, (window.devicePixelRatio || 1) * scale));
    var bw = Math.max(1, Math.round(w * ratio)), bh = Math.max(1, Math.round(h * ratio));
    if (canvas.width !== bw) canvas.width = bw;
    if (canvas.height !== bh) canvas.height = bh;
    var ctx = canvas.getContext('2d');
    ctx.setTransform(bw / w, 0, 0, bh / h, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.lineCap = 'butt';
    ctx.lineJoin = 'round';
    return { ctx: ctx, w: w, h: h };
  }
  function rrect(ctx, x, y, w, h, r) {
    r = Math.max(0, Math.min(r, w / 2, h / 2));
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }
  function fillRR(ctx, x, y, w, h, r, color) { rrect(ctx, x, y, w, h, r); ctx.fillStyle = color; ctx.fill(); }
  function font(ctx, px, bold) {
    ctx.font = (bold ? 'bold ' : '') + px + 'px ' + S.family;
    /* Qt's 11 px regular runs ~0.28 px a letter wider than the browser's. */
    if ('letterSpacing' in ctx) ctx.letterSpacing = (!bold && px === 11) ? '0.28px' : '0px';
  }
  /* Text with its baseline at y; align left / center / right on x. */
  function text(ctx, x, y, s, color, align, px, bold) {
    font(ctx, px || 11, bold);
    ctx.fillStyle = color;
    ctx.textAlign = align || 'left';
    ctx.textBaseline = 'alphabetic';
    ctx.fillText(s, x, y);
  }
  function line(ctx, x0, y0, x1, y1, color, width) {
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1);
    ctx.strokeStyle = color; ctx.lineWidth = width || 1; ctx.stroke();
  }
  function elide(ctx, s, maxW) {
    if (ctx.measureText(s).width <= maxW) return s;
    while (s.length > 1 && ctx.measureText(s + '…').width > maxW) s = s.slice(0, -1);
    return s + '…';
  }
  /* A filled area under a line (the sparkline and the toy lanes). */
  function areaLine(ctx, pts, base, fill, stroke, width) {
    var i;
    ctx.beginPath();
    ctx.moveTo(pts[0][0], base);
    for (i = 0; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.lineTo(pts[pts.length - 1][0], base);
    ctx.closePath();
    ctx.fillStyle = fill; ctx.fill();
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.strokeStyle = stroke; ctx.lineWidth = width; ctx.lineJoin = 'round'; ctx.lineCap = 'square';
    ctx.stroke();
    ctx.lineCap = 'butt';
  }

  /* ── Sparkline (22 px tall, on each session row) ──────────────────────── */

  function drawSpark(canvas, vals) {
    var g = prep(canvas, 22);
    if (!g) return;
    var ctx = g.ctx, w = g.w, h = g.h, C = colors(), base = h - 1, n = vals.length;
    if (!n) { line(ctx, 0, base, w, base, css(C['green-mid']), 1); return; }
    var pts = vals.map(function (v, k) {
      return [(k + 0.5) / n * w, base - Math.max(0, Math.min(1, v)) * (h - 3)];
    });
    if (n === 1) pts = [[0, pts[0][1]], [w, pts[0][1]]];
    areaLine(ctx, pts, base, css(C.green, 0.32), css(C.green), 1.5);
  }

  /* ── Weekday x hour heatmap ───────────────────────────────────────────── */

  var WK = { LEFT: 38, TOP: 4, ROW: 20, BARS_H: 40, RIGHT_W: 112 };

  function weekLayout(w) {
    var right = w >= 560 ? WK.RIGHT_W : 0;
    var gridW = w - WK.LEFT - right - (right ? 12 : 4);
    var pitch = Math.max(8, gridW / 24);
    return { right: right, pitch: pitch, gridR: WK.LEFT + pitch * 24 };
  }
  function weekBase() { return WK.TOP + 7 * WK.ROW + 12 + WK.BARS_H; }

  function drawWeek() {
    var g = prep(S.el.week, 214);
    if (!g) return;
    var ctx = g.ctx, C = colors(), L = weekLayout(g.w), pitch = L.pitch;
    var act = S.pattern.active, d, h;
    var rows = act.map(function (r) { return r.reduce(function (a, b) { return a + b; }, 0); });
    var cols = [];
    for (h = 0; h < 24; h++) { var s = 0; for (d = 0; d < 7; d++) s += act[d][h]; cols.push(s); }
    var cellMax = Math.max.apply(null, act.map(function (r) { return Math.max.apply(null, r); }));
    var rowMax = Math.max.apply(null, rows), colMax = Math.max.apply(null, cols);
    var green = css(C.green), muted = css(C.muted), dim = css(C.dim), txt = css(C.txt);

    for (d = 0; d < 7; d++) {
      var y = WK.TOP + d * WK.ROW;
      text(ctx, WK.LEFT - 6, y + 13, WEEKDAYS[d], muted, 'right');
      for (h = 0; h < 24; h++) {
        fillRR(ctx, WK.LEFT + h * pitch, y, pitch - 2, WK.ROW - 2, 3,
          css(ramp(C, cellMax ? act[d][h] / cellMax : 0)));
      }
      if (L.right && rowMax > 0) {
        var bw = Math.max(2, rows[d] / rowMax * (L.right - 46));
        fillRR(ctx, L.gridR + 12, y + 3, bw, 12, 3, green);
        if (rows[d] === rowMax) text(ctx, L.gridR + 12 + bw + 5, y + 13, fmtShort(rows[d]), txt);
      }
    }
    if (L.right) text(ctx, L.gridR + 12, WK.TOP + 7 * WK.ROW + 12, 'by weekday', dim);

    var base = weekBase();
    if (colMax > 0) {
      for (h = 0; h < 24; h++) {
        if (cols[h] <= 0) continue;
        var bh = Math.max(2, cols[h] / colMax * WK.BARS_H);
        fillRR(ctx, WK.LEFT + h * pitch + pitch * 0.2, base - bh, pitch * 0.6 - 2, bh, 2, green);
      }
      var peak = cols.indexOf(colMax);
      text(ctx, WK.LEFT + peak * pitch + (pitch - 2) / 2, base - WK.BARS_H - 3, 'peak', txt, 'center');
    }
    [0, 6, 12, 18, 23].forEach(function (hh) {
      text(ctx, WK.LEFT + hh * pitch + (pitch - 2) / 2, base + 14, p2(hh), dim, 'center');
    });
    text(ctx, WK.LEFT - 6, base - 2, 'hour', dim, 'right');

    if (cellMax <= 0) {
      var msg = 'Nothing recorded here yet. This fills in as you play.';
      font(ctx, 12);
      var tw = ctx.measureText(msg).width + 20;
      var cx = (WK.LEFT + L.gridR) / 2, cy = WK.TOP + 3.5 * WK.ROW;
      rrect(ctx, cx - tw / 2, cy - 14, tw, 26, 8);
      ctx.fillStyle = css(C.card); ctx.fill();
      ctx.strokeStyle = css(C['green-mid']); ctx.lineWidth = 1; ctx.stroke();
      ctx.fillStyle = muted; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(msg, cx, cy - 1);
    }
  }
  function weekHit(x, y, w) {
    var L = weekLayout(w), act = S.pattern.active, thr = S.pattern.thrusts;
    var span = ' ' + SPANS[S.span][1], d, h, a, t, dd;
    function sum(arr) { return arr.reduce(function (p, c) { return p + c; }, 0); }
    if (x >= WK.LEFT && x < L.gridR) {
      h = Math.floor((x - WK.LEFT) / L.pitch);
      d = Math.floor((y - WK.TOP) / WK.ROW);
      if (d >= 0 && d < 7 && h >= 0 && h < 24 && y >= WK.TOP) {
        return '<b>' + WEEKDAYS[d] + ' ' + p2(h) + ':00–' + p2((h + 1) % 24) + ':00</b>' + span +
          '<br>' + fmtShort(act[d][h]) + ' active · ' + num(thr[d][h]) + ' thrusts';
      }
      var base = weekBase();
      if (h >= 0 && h < 24 && y >= base - WK.BARS_H - 14 && y <= base + 16) {
        a = 0; t = 0;
        for (dd = 0; dd < 7; dd++) { a += act[dd][h]; t += thr[dd][h]; }
        return '<b>' + p2(h) + ':00–' + p2((h + 1) % 24) + ':00, every day</b>' + span +
          '<br>' + fmtShort(a) + ' active · ' + num(t) + ' thrusts';
      }
    }
    if (L.right && x >= L.gridR + 8) {
      d = Math.floor((y - WK.TOP) / WK.ROW);
      if (d >= 0 && d < 7 && y >= WK.TOP) {
        return '<b>' + WEEKDAYS_LONG[d] + '</b>' + span + '<br>' + fmtShort(sum(act[d])) +
          ' active · ' + num(sum(thr[d])) + ' thrusts';
      }
    }
    return null;
  }

  /* ── Month calendar (290 x 218) ───────────────────────────────────────── */

  var CAL = { CW: 38, CH: 30, GAP: 4, HEAD: 18 };

  function calCell(year, month, dayN) {
    var first = weekday(new Date(Date.UTC(year, month - 1, 1)));
    var i = first + dayN - 1;
    return [(i % 7) * (CAL.CW + CAL.GAP), CAL.HEAD + Math.floor(i / 7) * (CAL.CH + CAL.GAP)];
  }
  function drawCal() {
    var g = prep(S.el.cal, 218);
    if (!g) return;
    var ctx = g.ctx, C = colors(), y = S.month[0], m = S.month[1], days = S.monthData;
    ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'].forEach(function (name, i) {
      text(ctx, i * (CAL.CW + CAL.GAP) + CAL.CW / 2, 12, name, css(C.dim), 'center');
    });
    var top = 0, k;
    for (k in days) top = Math.max(top, days[k].active_s);
    for (var d = 1; d <= daysIn(y, m); d++) {
      var xy = calCell(y, m, d), v = days[d] ? days[d].active_s : 0, t = top ? v / top : 0;
      fillRR(ctx, xy[0], xy[1], CAL.CW, CAL.CH, 5, css(ramp(C, v > 0 ? t : 0)));
      var today = DATA.today[0] === y && DATA.today[1] === m && DATA.today[2] === d;
      if (today) {
        rrect(ctx, xy[0] + 0.75, xy[1] + 0.75, CAL.CW - 1.5, CAL.CH - 1.5, 5);
        ctx.strokeStyle = css(C.accent); ctx.lineWidth = 1.5; ctx.stroke();
      }
      var color = t > 0.6 ? C.ink : (today ? C.txt : C.muted);
      text(ctx, xy[0] + 5, xy[1] + 13, String(d), css(color), 'left', 11, today);
    }
  }
  function calHit(x, y) {
    var yy = S.month[0], m = S.month[1];
    for (var d = 1; d <= daysIn(yy, m); d++) {
      var xy = calCell(yy, m, d);
      if (x >= xy[0] && x < xy[0] + CAL.CW && y >= xy[1] && y < xy[1] + CAL.CH) {
        var e = S.monthData[d] || { active_s: 0, thrusts: 0, sessions: 0 };
        var when = new Date(Date.UTC(yy, m - 1, d));
        var head = WEEKDAYS[weekday(when)] + ' ' + d + ' ' + MONTHS[m - 1], body = 'nothing';
        if (e.active_s > 0 || e.sessions) {
          body = fmtShort(e.active_s) + ' active · ' + num(e.thrusts) + ' thrusts' +
            (e.sessions ? ' · ' + e.sessions + ' session' + (e.sessions !== 1 ? 's' : '') : '');
        }
        return '<b>' + head + '</b><br>' + body;
      }
    }
    return null;
  }

  /* ── One session over time ────────────────────────────────────────────── */

  var TL = {
    LABEL_W: 116, TOP: 20, TOY_H: 36, TOY_GAP: 8, THR_H: 44, THR_GAP: 12,
    CAPTION_H: 16, ZONE_H: 14, ZONE_GAP: 6, AXIS_H: 20, MIN_COL_PX: 3
  };

  function timelineModel(s) {
    var toys = Object.keys(s.lv).sort(function (a, b) {
      return ((s.toys[b] || 0) - (s.toys[a] || 0)) || byName(a, b);
    });
    var zones = Object.keys(s.zr).sort(function (a, b) {
      return ((s.zones[b] || 0) - (s.zones[a] || 0)) || byName(a, b);
    });
    var lv = {};
    toys.forEach(function (name) { lv[name] = decode(s.lv[name]).map(function (q) { return q / 35; }); });
    return {
      s: s, toys: toys, zones: zones, lv: lv, thr: decode(s.thr),
      height: TL.TOP + toys.length * (TL.TOY_H + TL.TOY_GAP) + TL.THR_H + TL.THR_GAP +
        (zones.length ? TL.CAPTION_H + zones.length * (TL.ZONE_H + TL.ZONE_GAP) : 0) + TL.AXIS_H
    };
  }
  function tlColumns(n, pw) {
    var c = Math.max(1, Math.min(n, Math.floor(pw / TL.MIN_COL_PX))), out = [];
    for (var k = 0; k < c; k++) {
      var a = Math.floor(k * n / c);
      out.push([a, Math.max(a + 1, Math.floor((k + 1) * n / c))]);
    }
    return out;
  }
  function mean(arr, a, b) { var t = 0; for (var i = a; i < b; i++) t += arr[i]; return t / (b - a); }
  function total(arr, a, b) { var t = 0; for (var i = a; i < b; i++) t += arr[i]; return t; }

  function drawTimeline() {
    var M = S.tl;
    if (!M) return;
    S.el.timeline.style.height = M.height + 'px';
    var g = prep(S.el.timeline, M.height);
    if (!g) return;
    var ctx = g.ctx, C = colors(), s = M.s, a = s.an;
    var left = TL.LABEL_W, pw = Math.max(10, g.w - left - 6), right = left + pw;
    var n = s.n, bs = s.bucket_s, cols = tlColumns(n, pw);
    var txt = css(C.txt), muted = css(C.muted), dim = css(C.dim), mid = C['green-mid'];
    var bottom = g.h - TL.AXIS_H;
    function xOf(k) { return left + k / Math.max(1, n) * pw; }

    /* Time grid + axis, under everything. */
    var spanS = n * bs, pxPerS = spanS ? pw / spanS : 1, step = 21600;
    [60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600].some(function (v) {
      if (v * pxPerS >= 72) { step = v; return true; }
      return false;
    });
    var t0 = s.start + s.start_i * bs;
    font(ctx, 11);
    var halfLabel = ctx.measureText('00:00').width / 2 + 1;
    for (var tick = Math.ceil(t0 / step) * step; tick <= t0 + spanS; tick += step) {
      var x = left + (tick - t0) * pxPerS;
      line(ctx, x, TL.TOP - 4, x, bottom, css(mid, 0.55), 1);
      text(ctx, Math.min(Math.max(x, left + halfLabel), g.w - halfLabel), bottom + 15, clock(tick), dim, 'center');
    }

    /* The hottest five minutes, behind the lanes. */
    if (a.hot_len_s) {
      var k0 = a.hot_at_s / bs - s.start_i;
      var hx0 = xOf(k0), hx1 = xOf(k0 + a.hot_len_s / bs);
      ctx.fillStyle = css(C.txt, 0.07);
      ctx.fillRect(hx0, TL.TOP - 4, Math.max(3, hx1 - hx0), bottom - TL.TOP + 4);
      var label = a.hot_kind === 'thrusts' ? 'hottest 5 min' : 'most intense 5 min';
      font(ctx, 11);
      var half = ctx.measureText(label).width / 2;
      text(ctx, Math.min(right - half, Math.max(left + half, (hx0 + hx1) / 2)), TL.TOP - 8, label, txt, 'center');
    }

    var y = TL.TOP, base;
    /* Toy intensity lanes. */
    M.toys.forEach(function (name, idx) {
      var vals = M.lv[name], color = toyColor(C, idx);
      base = y + TL.TOY_H;
      text(ctx, 0, y + 15, name, txt, 'left', 11, true);
      text(ctx, 0, y + 29, 'intensity', dim);
      line(ctx, left, base, right, base, css(mid), 1);
      var pts = cols.map(function (c) {
        return [xOf((c[0] + c[1]) / 2), base - mean(vals, c[0], c[1]) * (TL.TOY_H - 4)];
      });
      if (pts.length) areaLine(ctx, pts, base, css(color, 0.25), css(color), 2);
      y += TL.TOY_H + TL.TOY_GAP;
    });

    /* Thrusts per minute. */
    base = y + TL.THR_H;
    var rates = cols.map(function (c) { return total(M.thr, c[0], c[1]) * 60 / ((c[1] - c[0]) * bs); });
    var topRate = rates.length ? Math.max.apply(null, rates) : 0;
    text(ctx, 0, y + 15, 'Thrusts', txt, 'left', 11, true);
    text(ctx, 0, y + 29, topRate ? 'up to ' + r0(topRate) + '/min' : 'none', dim);
    line(ctx, left, base, right, base, css(mid), 1);
    if (topRate > 0) {
      var pink = css(C.pink);
      cols.forEach(function (c, i) {
        if (rates[i] <= 0) return;
        var x0 = xOf(c[0]), x1 = xOf(c[1]);
        var bh = Math.max(2, rates[i] / topRate * (TL.THR_H - 4)), bw = Math.max(1, x1 - x0 - 1);
        fillRR(ctx, x0, base - bh, bw, bh, Math.min(2, bw / 2), pink);
      });
    }
    y += TL.THR_H + TL.THR_GAP;

    /* Contact lanes. */
    if (M.zones.length) {
      text(ctx, 0, y + 11, 'Contact', txt, 'left', 11, true);
      y += TL.CAPTION_H;
      M.zones.forEach(function (key) {
        fillRR(ctx, left, y, pw, TL.ZONE_H, 3, css(C.well));
        font(ctx, 11);
        text(ctx, 0, y + 11, elide(ctx, zoneLabel(key), TL.LABEL_W - 8), muted);
        var fill = css(zoneColor(C, key), 0.9);
        s.zr[key].forEach(function (run) {
          var x0 = xOf(run[0]), x1 = xOf(run[1]);
          fillRR(ctx, x0, y, Math.max(2, x1 - x0), TL.ZONE_H, 3, fill);
        });
        y += TL.ZONE_H + TL.ZONE_GAP;
      });
    }

    /* Hover crosshair. */
    if (S.hoverCol !== null && S.hoverCol < cols.length) {
      var hc = cols[S.hoverCol], hx = xOf((hc[0] + hc[1]) / 2);
      line(ctx, hx, TL.TOP - 4, hx, bottom, muted, 1);
    }
  }
  function timelineHit(x, w) {
    var M = S.tl, s = M.s, left = TL.LABEL_W, pw = Math.max(10, w - left - 6);
    var cols = tlColumns(s.n, pw);
    if (!cols.length || x < left || x > left + pw) return null;
    var k = Math.min(s.n - 1, Math.max(0, Math.floor((x - left) / pw * s.n))), col = -1;
    for (var i = 0; i < cols.length; i++) if (cols[i][0] <= k && k < cols[i][1]) { col = i; break; }
    if (col < 0) return null;
    var a = cols[col][0], b = cols[col][1];
    var lines = ['<b>' + clock(s.start + (s.start_i + a) * s.bucket_s) + '</b>'];
    M.toys.forEach(function (name, idx) {
      lines.push('<span class="st-dot-' + TOY_HUES[idx % 3] + '">&#9632;</span> ' + esc(name) + ' ' +
        r0(mean(M.lv[name], a, b) * 100) + '%');
    });
    lines.push('<span class="st-dot-pink">&#9632;</span> ' +
      r0(total(M.thr, a, b) * 60 / ((b - a) * s.bucket_s)) + ' thrusts/min');
    var touching = M.zones.filter(function (z) {
      return s.zr[z].some(function (run) { return run[0] < b && run[1] > a; });
    }).map(zoneLabel);
    lines.push(touching.length ? touching.map(esc).join(', ') : 'no contact');
    return { col: col, html: lines.join('<br>') };
  }

  /* ── DOM ──────────────────────────────────────────────────────────────── */

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function make(tag, cls, txt) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }
  function tile(caption, value, note) {
    var t = make('div', 'st-tile');
    t.appendChild(make('div', 'st-cap', caption));
    t.appendChild(make('div', 'st-val', value));
    if (note) t.appendChild(make('div', 'st-note', note));
    return t;
  }
  function q(name) { return S.root.querySelector('[data-st="' + name + '"]'); }

  function fillSessions() {
    var list = S.el.list;
    list.textContent = '';
    S.sparks = [];
    DATA.sessions.forEach(function (s) {
      var row = make('div', 'st-row');
      row.setAttribute('role', 'button');
      row.tabIndex = 0;
      row.dataset.id = s.id;
      row.appendChild(make('span', 'st-when', day(s.start) + '  ' + clock(s.start)));
      row.appendChild(make('span', 'st-c st-c-dur', fmtShort(s.duration_s)));
      row.appendChild(make('span', 'st-c st-c-act', fmtShort(s.active_s) + ' active'));
      row.appendChild(make('span', 'st-c st-c-thr', num(s.thrusts) + ' thrusts'));
      var spark = make('canvas', 'st-spark');
      row.appendChild(spark);
      row.appendChild(make('span', 'st-chev', '›'));
      list.appendChild(row);
      S.sparks.push([spark, s.spark]);
    });
  }

  function fillLifetime() {
    var life = DATA.lifetime, f = DATA.facts;
    q('life-active').textContent = fmtDur(life.active_s);
    q('life-thrusts').textContent = num(life.thrusts);
    q('life-sessions').textContent = num(life.sessions);
    var d = dt(DATA.app_started);
    q('this-session').textContent = 'This session: 0s active  •  0 thrusts  •  started ' +
      d.getUTCFullYear() + '-' + p2(d.getUTCMonth() + 1) + '-' + p2(d.getUTCDate()) + ' ' + clock(DATA.app_started);

    var facts = q('facts');
    facts.textContent = '';
    [
      ['Average session', fmtShort(f.avg_session_s), 'active, ' + num(r0(f.avg_session_thrusts)) + ' thrusts'],
      ['Average pace', r0(f.pace) + ' / min', 'thrusts per active minute'],
      ['Favourite toy', f.fav_toy[0], pct(f.fav_toy[1]) + ' of all toy time'],
      ['Favourite spot', zoneLabel(f.fav_zone[0]), pct(f.fav_zone[1]) + ' of all contact'],
      ['Night owl', pct(f.night_share), 'of your play is between 22:00 and 04:00'],
      ['Busiest day', WEEKDAYS_LONG[f.busiest_weekday], 'by active time'],
      ['Best session', num(f.best_session[0]) + ' thrusts', day(f.best_session[1])],
      ['Longest session', fmtShort(f.longest_session[0]) + ' active', day(f.longest_session[1])],
      ['Record pace', f.record_pace[0] + ' / min', 'thrusts in one minute, ' + day(f.record_pace[1])]
    ].forEach(function (t) { facts.appendChild(tile(t[0], t[1], t[2])); });

    table(q('toys'), Object.keys(life.toys).sort(byName).map(function (name) {
      return [name, life.toys[name]];
    }));
    table(q('zones'), Object.keys(life.zones).sort(byName).map(function (key) {
      return [zoneLabel(key), life.zones[key]];
    }));
  }
  function table(host, rows) {
    host.textContent = '';
    ['', 'Lifetime', 'This session', ''].forEach(function (h) { host.appendChild(make('span', 'st-th', h)); });
    rows.forEach(function (r) {
      host.appendChild(make('span', 'st-td-n', r[0]));
      host.appendChild(make('span', 'st-td-l', fmtDur(r[1])));
      host.appendChild(make('span', 'st-td-s', fmtDur(0)));
      host.appendChild(make('span', ''));
    });
  }

  function fillPatterns() {
    S.pattern = weekdayHour(SPANS[S.span][0]);
    var keys = Object.keys(DATA.hours).sort();
    var first = keys[0];
    var since = Date.UTC(+first.slice(0, 4), +first.slice(5, 7) - 1, +first.slice(8, 10)) / 1000;
    q('week-hint').textContent = 'Recording by the hour since ' + day(since) + ' ' + first.slice(0, 4) +
      '. Hover a cell or a bar for the numbers.';
    S.root.querySelectorAll('[data-span]').forEach(function (b) {
      b.classList.toggle('is-on', +b.dataset.span === S.span);
    });
    drawWeek();
  }

  function fillMonth() {
    var y = S.month[0], m = S.month[1], days = monthDays(y, m), k;
    S.monthData = days;
    q('month-label').textContent = MONTHS_LONG[m - 1] + ' ' + y;
    var active = 0, thrusts = 0, sessions = 0, played = [];
    for (k in days) {
      active += days[k].active_s; thrusts += days[k].thrusts; sessions += days[k].sessions;
      if (days[k].active_s > 0) played.push(+k);
    }
    q('m-active').textContent = fmtShort(active);
    q('m-thrusts').textContent = num(thrusts);
    q('m-sessions').textContent = num(sessions);
    q('m-days').textContent = String(played.length);
    q('m-days-note').textContent = 'of ' + daysIn(y, m);
    if (played.length) {
      var best = played.reduce(function (a, b) { return days[b].active_s > days[a].active_s ? b : a; });
      q('m-best').textContent = day(Date.UTC(y, m - 1, best) / 1000);
      q('m-best-note').textContent = fmtShort(days[best].active_s) + ' active';
      q('m-avg').textContent = fmtShort(active / played.length);
      q('m-avg-note').textContent = num(r0(thrusts / played.length)) + ' thrusts';
    } else {
      q('m-best').textContent = '—';
      q('m-best-note').textContent = 'nothing this month';
      q('m-avg').textContent = '—';
      q('m-avg-note').textContent = '';
    }
    drawCal();
  }

  function fillDetail(s) {
    var a = s.an, end = s.start + s.duration_s;
    q('detail-title').textContent = day(s.start) + '  ' + clock(s.start) + ' to ' + clock(end) +
      '  ·  app open ' + fmtShort(s.duration_s);
    var w0 = s.start + a.window_start_s;
    var perMin = s.active_s >= 60 ? s.thrusts / (s.active_s / 60) : 0;
    var tiles = q('detail-tiles');
    tiles.textContent = '';
    tiles.appendChild(tile('Active', fmtShort(s.active_s),
      (a.window_s ? pct(s.active_s / a.window_s) + ' of ' : '') + clock(w0) + ' to ' + clock(w0 + a.window_s)));
    tiles.appendChild(tile('Thrusts', num(s.thrusts), perMin ? r0(perMin) + ' per active minute' : ''));
    tiles.appendChild(tile('Peak pace', a.peak_pace ? a.peak_pace + ' / min' : '—',
      a.peak_pace ? 'at ' + clock(s.start + a.peak_pace_at_s) : 'no thrusts'));
    tiles.appendChild(tile('Longest streak', fmtShort(a.streak_s), 'without a real break'));

    S.tl = timelineModel(s);
    S.hoverCol = null;

    /* The analysis lines (statistics._stats_fill_insights). */
    var lines = [];
    if (a.hot_len_s) {
      var t0 = s.start + a.hot_at_s, t1 = t0 + a.hot_len_s;
      lines.push(a.hot_kind === 'thrusts'
        ? 'Hottest 5 minutes: ' + clock(t0) + ' to ' + clock(t1) + ', ' + num(a.hot_value) + ' thrusts.'
        : 'Most intense 5 minutes: ' + clock(t0) + ' to ' + clock(t1) + ', toys at ' + pct(a.hot_value) + ' on average.');
    }
    if (a.top_toy) {
      lines.push(esc(a.top_toy) + ' did ' + pct(a.top_toy_share) + ' of the buzzing, at ' +
        pct(a.top_toy_level) + ' on average.');
    }
    if (a.break_s) lines.push('Longest break: ' + fmtShort(a.break_s) + ', from ' + clock(s.start + a.break_at_s) + '.');
    if (a.top_zone) lines.push('Most contact: ' + esc(zoneLabel(a.top_zone)) + ', ' + fmtShort(a.top_zone_s) + '.');
    var toys = byAmount(s.toys);
    if (toys.length) {
      lines.push('Toy time: ' + toys.map(function (name) {
        var lane = S.tl.toys.indexOf(name);
        var dot = lane >= 0 ? '<span class="st-dot-' + TOY_HUES[lane % 3] + '">&#9632;</span> ' : '';
        return dot + esc(name) + ' ' + fmtShort(s.toys[name]);
      }).join(' · '));
    }
    var zones = byAmount(s.zones);
    if (zones.length) {
      lines.push('Contact: ' + zones.map(function (z) {
        return esc(zoneLabel(z)) + ' ' + fmtShort(s.zones[z]);
      }).join(' · '));
    }
    if (!lines.length) lines.push('Nothing much happened in this one.');
    var host = q('insights');
    host.textContent = '';
    lines.forEach(function (html) { var d = make('div'); d.innerHTML = html; host.appendChild(d); });
  }

  /* ── the two pages ────────────────────────────────────────────────────── */

  function openSession(id) {
    var s = sessionById(id);
    if (!s || !S.root) return;
    hideTip();
    S.listScroll = S.root.scrollTop;
    S.detail = id;
    fillDetail(s);
    S.el.overview.hidden = true;
    S.el.detail.hidden = false;
    S.root.scrollTop = 0;
    drawTimeline();
  }
  function showOverview() {
    if (!S.root) return;
    hideTip();
    S.detail = null;
    S.tl = null;
    S.el.detail.hidden = true;
    S.el.overview.hidden = false;
    S.root.scrollTop = S.listScroll;
    redraw();
  }

  /* ── tooltips ─────────────────────────────────────────────────────────── */

  /* Pointer position in the page's own pixels (the app window may be scaled). */
  function local(ev, node) {
    var r = node.getBoundingClientRect();
    var k = r.width > 0 && node.offsetWidth ? node.offsetWidth / r.width : 1;
    return [(ev.clientX - r.left) * k, (ev.clientY - r.top) * k];
  }
  function showTip(ev, html, nowrap) {
    var tip = S.el.tip, root = S.root;
    tip.innerHTML = html;
    tip.classList.toggle('st-tip-nowrap', !!nowrap);
    tip.hidden = false;
    var p = local(ev, root);
    var x = p[0] + 14, y = p[1] + 18;
    x = Math.max(4, Math.min(x, root.clientWidth - tip.offsetWidth - 4));
    if (y + tip.offsetHeight > root.clientHeight - 4) y = p[1] - tip.offsetHeight - 8;
    tip.style.left = x + 'px';
    tip.style.top = (Math.max(4, y) + root.scrollTop) + 'px';
  }
  function hideTip() {
    clearTimeout(S.tipTimer);
    if (S.el.tip) S.el.tip.hidden = true;
  }
  function chartTips(canvas, hit, after) {
    canvas.addEventListener('mousemove', function (ev) {
      var p = local(ev, canvas), html = hit(p[0], p[1], canvas.clientWidth);
      if (html) showTip(ev, html, true); else hideTip();
    });
    canvas.addEventListener('mouseleave', function () { hideTip(); if (after) after(); });
  }
  /* Explanations: rest the pointer for ~0.7 s, like Qt's. */
  function restTips(root) {
    root.addEventListener('mouseover', function (ev) {
      var t = ev.target.closest ? ev.target.closest('[data-st-tip]') : null;
      if (!t || !root.contains(t)) return;
      clearTimeout(S.tipTimer);
      S.tipTimer = setTimeout(function () {
        var title = t.getAttribute('data-st-tiptitle');
        showTip(ev, (title ? '<b>' + esc(title) + '</b><br>' : '') + t.getAttribute('data-st-tip'), false);
      }, 700);
    });
    root.addEventListener('mouseout', function (ev) {
      var t = ev.target.closest ? ev.target.closest('[data-st-tip]') : null;
      if (t && (!ev.relatedTarget || !t.contains(ev.relatedTarget))) hideTip();
    });
  }

  /* ── wiring ───────────────────────────────────────────────────────────── */

  var pending = 0;
  function redrawSoon() {
    if (pending) return;
    pending = (window.requestAnimationFrame || setTimeout)(function () { pending = 0; redraw(); });
  }
  function redraw() {
    if (!S.root) return;
    S.colors = null;                       /* read the tokens afresh */
    if (S.detail) { drawTimeline(); return; }
    S.sparks.forEach(function (p) { drawSpark(p[0], p[1]); });
    drawWeek();
    drawCal();
  }

  function init(rootElement) {
    var root = rootElement || document.querySelector('.pg-stats');
    if (root && !(root.classList && root.classList.contains('pg-stats'))) root = root.querySelector('.pg-stats');
    if (!root || root === S.root) { redraw(); return; }
    S.root = root;
    S.el = {
      overview: q('overview'), detail: q('detail'), list: q('list'), week: q('week'),
      cal: q('cal'), timeline: q('timeline'), tip: q('tip')
    };
    S.el.probe = make('span');
    S.el.probe.style.display = 'none';
    root.appendChild(S.el.probe);
    S.month = [DATA.today[0], DATA.today[1]];
    S.span = 1;

    fillSessions();
    fillLifetime();
    fillPatterns();
    fillMonth();

    S.el.list.addEventListener('click', function (ev) {
      var row = ev.target.closest('.st-row');
      if (row) openSession(row.dataset.id);
    });
    S.el.list.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
      var row = ev.target.closest('.st-row');
      if (row) { ev.preventDefault(); openSession(row.dataset.id); }
    });
    q('back').addEventListener('click', showOverview);
    root.querySelectorAll('[data-span]').forEach(function (b) {
      b.addEventListener('click', function () { S.span = +b.dataset.span; S.colors = null; fillPatterns(); });
    });
    root.querySelectorAll('[data-month]').forEach(function (b) {
      b.addEventListener('click', function () {
        var m = S.month[1] + (+b.dataset.month), y = S.month[0];
        if (m < 1) { y -= 1; m = 12; } else if (m > 12) { y += 1; m = 1; }
        S.month = [y, m];
        S.colors = null;
        fillMonth();
      });
    });

    chartTips(S.el.week, weekHit);
    chartTips(S.el.cal, calHit);
    S.el.timeline.addEventListener('mousemove', function (ev) {
      if (!S.tl) return;
      var p = local(ev, S.el.timeline), hit = timelineHit(p[0], S.el.timeline.clientWidth);
      if (!hit) { if (S.hoverCol !== null) { S.hoverCol = null; drawTimeline(); } hideTip(); return; }
      if (hit.col !== S.hoverCol) { S.hoverCol = hit.col; drawTimeline(); }
      showTip(ev, hit.html, true);
    });
    S.el.timeline.addEventListener('mouseleave', function () {
      if (S.hoverCol !== null) { S.hoverCol = null; drawTimeline(); }
      hideTip();
    });
    restTips(root);
    root.addEventListener('scroll', hideTip);

    /* Repaint when the page gets its size (it may be built while hidden),
       when the window is resized (the app window is scaled to fit), when
       the fonts arrive, and when a colour token changes on an ancestor. */
    if (window.ResizeObserver) new ResizeObserver(redrawSoon).observe(root);
    window.addEventListener('resize', redrawSoon);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(redrawSoon);
    if (window.MutationObserver) {
      var mo = new MutationObserver(redrawSoon);
      for (var n = root; n && n.nodeType === 1; n = n.parentNode) {
        mo.observe(n, { attributes: true, attributeFilter: ['style', 'class', 'data-theme'] });
      }
    }
    redraw();
  }

  window.OGPDemoStats = {
    init: init,
    redraw: redraw,
    /* extras: jump to a session's page / back to the list */
    openSession: openSession,
    showOverview: showOverview,
    sessions: function () { return DATA.sessions.map(function (s) { return s.id; }); }
  };
})();

// The page's markup (stats.html), so the demo can mount it without a request.
window.OGPDemoStats.HTML = "<div class=\"pg pg-stats\">\n  <div class=\"st-page\">\n    <div class=\"st-title\">Statistics</div>\n\n    <!-- ── the overview: sessions, lifetime, when you play, month ── -->\n    <div class=\"st-overview\" data-st=\"overview\">\n      <div class=\"st-muted\">How much your gear actually gets used, and when. Sampled once per second; nothing here touches the haptic path.</div>\n\n      <section class=\"st-card\">\n        <div class=\"st-head\">\n          <div class=\"st-sec\" data-st-tiptitle=\"Sessions\" data-st-tip=\"Every app run that saw activity, newest first. The graph is how busy each part of it was. Click a session for its timeline: each toy's intensity, thrusts per minute, which zones were touched, and a short analysis.&lt;br&gt;&lt;br&gt;With no toy running, stray contacts don't start a session: contact only counts once it adds up to 20 thrusts without a pause longer than 10 seconds, or to a minute of touching within three minutes. Strokes counted while nothing is touching you never count.\">Sessions</div>\n        </div>\n        <div class=\"st-list\" data-st=\"list\"></div>\n      </section>\n\n      <section class=\"st-card\">\n        <div class=\"st-head\">\n          <div class=\"st-sec\" data-st-tiptitle=\"Lifetime statistics\" data-st-tip=\"What counts: a toy is &lt;b&gt;on&lt;/b&gt; while any of its motors is driven above zero; a zone is &lt;b&gt;in contact&lt;/b&gt; while any of its OGB signals reads above zero; &lt;b&gt;active time&lt;/b&gt; ticks while either is true. One full in-out stroke = one &lt;b&gt;thrust&lt;/b&gt;. Everything is sampled once per second, so sub-second blips can round away. Sessions are app runs that saw any activity.&lt;br&gt;&lt;br&gt;While no toy is running, contact is held back until it turns into a real scene: 20 thrusts with no pause longer than 10 seconds, or a minute of touching within three minutes (one long touch or many short ones), and a stroke only counts while something is touching you. Then the 30 seconds before it count as well, and it keeps counting until half an hour of quiet. Stray contacts and lone strokes never count.\">Lifetime</div>\n          <button type=\"button\" class=\"st-btn\" data-st=\"reset\" data-st-tip=\"Zero every statistic, session and chart. Asks first.\">Reset</button>\n        </div>\n        <div class=\"st-tiles st-cols-3\">\n          <div class=\"st-tile\"><div class=\"st-cap\">Total active time</div><div class=\"st-val\" data-st=\"life-active\">—</div></div>\n          <div class=\"st-tile\"><div class=\"st-cap\">Thrusts</div><div class=\"st-val\" data-st=\"life-thrusts\">—</div></div>\n          <div class=\"st-tile\"><div class=\"st-cap\">Sessions</div><div class=\"st-val\" data-st=\"life-sessions\">—</div></div>\n        </div>\n        <div class=\"st-muted st-pre\" data-st=\"this-session\"></div>\n        <div class=\"st-h\">Fun facts</div>\n        <div class=\"st-tiles st-cols-3\" data-st=\"facts\"></div>\n        <div class=\"st-h\">Toys</div>\n        <div class=\"st-table\" data-st=\"toys\"></div>\n        <div class=\"st-h\">Zones</div>\n        <div class=\"st-table\" data-st=\"zones\"></div>\n      </section>\n\n      <section class=\"st-card\">\n        <div class=\"st-head\">\n          <div class=\"st-sec\" data-st-tiptitle=\"When you play\" data-st-tip=\"Active time by weekday and hour of the day. The brighter the cell, the more happened in that hour. The bars below add up every day per hour; the bars on the right add up each weekday. Hover anything for the numbers.\">When you play</div>\n          <button type=\"button\" class=\"st-btn st-seg\" data-span=\"0\">4 weeks</button>\n          <button type=\"button\" class=\"st-btn st-seg\" data-span=\"1\">3 months</button>\n          <button type=\"button\" class=\"st-btn st-seg\" data-span=\"2\">All time</button>\n        </div>\n        <canvas class=\"st-week\" data-st=\"week\"></canvas>\n        <div class=\"st-hint\" data-st=\"week-hint\"></div>\n      </section>\n\n      <section class=\"st-card\">\n        <div class=\"st-head\">\n          <div class=\"st-sec\">Month</div>\n          <button type=\"button\" class=\"st-btn\" data-month=\"-1\" data-st-tip=\"Previous month\">←</button>\n          <div class=\"st-month-label\" data-st=\"month-label\"></div>\n          <button type=\"button\" class=\"st-btn\" data-month=\"1\" data-st-tip=\"Next month\">→</button>\n        </div>\n        <div class=\"st-month\">\n          <canvas class=\"st-cal\" data-st=\"cal\"></canvas>\n          <div class=\"st-tiles st-cols-2\">\n            <div class=\"st-tile\"><div class=\"st-cap\">Active</div><div class=\"st-val\" data-st=\"m-active\">—</div></div>\n            <div class=\"st-tile\"><div class=\"st-cap\">Thrusts</div><div class=\"st-val\" data-st=\"m-thrusts\">—</div></div>\n            <div class=\"st-tile\"><div class=\"st-cap\">Sessions</div><div class=\"st-val\" data-st=\"m-sessions\">—</div></div>\n            <div class=\"st-tile\"><div class=\"st-cap\">Days with play</div><div class=\"st-val\" data-st=\"m-days\">—</div><div class=\"st-note\" data-st=\"m-days-note\"></div></div>\n            <div class=\"st-tile\"><div class=\"st-cap\">Best day</div><div class=\"st-val\" data-st=\"m-best\">—</div><div class=\"st-note\" data-st=\"m-best-note\"></div></div>\n            <div class=\"st-tile\"><div class=\"st-cap\">Average play day</div><div class=\"st-val\" data-st=\"m-avg\">—</div><div class=\"st-note\" data-st=\"m-avg-note\"></div></div>\n          </div>\n        </div>\n        <div class=\"st-hint\">Sessions from before the charts existed count on the day they started.</div>\n      </section>\n    </div>\n\n    <!-- ── one session's page (shown instead of the overview) ── -->\n    <div class=\"st-detail\" data-st=\"detail\" hidden>\n      <div class=\"st-head\">\n        <button type=\"button\" class=\"st-btn st-pre\" data-st=\"back\">←  All sessions</button>\n        <div class=\"st-sec st-pre\" data-st=\"detail-title\">Session</div>\n      </div>\n      <section class=\"st-card st-card-detail\">\n        <div class=\"st-tiles st-cols-4\" data-st=\"detail-tiles\"></div>\n        <canvas class=\"st-timeline\" data-st=\"timeline\"></canvas>\n        <div class=\"st-h\">Analysis</div>\n        <div class=\"st-insights\" data-st=\"insights\"></div>\n      </section>\n    </div>\n  </div>\n  <div class=\"st-tip\" data-st=\"tip\" hidden></div>\n</div>\n";
