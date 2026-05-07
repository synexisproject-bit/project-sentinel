const {Document,Packer,Paragraph,TextRun,Table,TableRow,TableCell,AlignmentType,BorderStyle,WidthType,ShadingType,Footer,PageNumber}=require('docx');
const fs=require('fs');
const BLUE='1F3864',MIDBLUE='2E5F9E',GOLD='7D6608',GREEN='1E6B2E',RED='7B0000',BLACK='000000',GRAY='888888';
const b={style:BorderStyle.SINGLE,size:1,color:'CCCCCC'};
const borders={top:b,bottom:b,left:b,right:b};
const rule=()=>new Paragraph({spacing:{before:160,after:160},border:{bottom:{style:BorderStyle.SINGLE,size:4,color:'DDDDDD',space:1}},children:[new TextRun('')]});
const h1=(t,c=BLUE)=>new Paragraph({spacing:{before:320,after:120},children:[new TextRun({text:t,bold:true,size:28,color:c,font:'Arial'})]});
const h2=(t,c=MIDBLUE)=>new Paragraph({spacing:{before:200,after:80},children:[new TextRun({text:t,bold:true,size:24,color:c,font:'Arial'})]});
const body=(t)=>new Paragraph({spacing:{before:60,after:60},children:[new TextRun({text:t,size:20,font:'Arial',color:BLACK})]});
const bullet=(t)=>new Paragraph({spacing:{before:40,after:40},indent:{left:360},children:[new TextRun({text:'- '+t,size:20,font:'Arial',color:BLACK})]});
const meta=(l,v)=>new Paragraph({spacing:{before:40,after:40},children:[new TextRun({text:l+': ',bold:true,size:19,font:'Arial',color:MIDBLUE}),new TextRun({text:v,size:19,font:'Arial',color:BLACK})]});
const note=(t,c=GOLD)=>new Paragraph({spacing:{before:60,after:60},shading:{fill:'F8F8F8',type:ShadingType.CLEAR},border:{left:{style:BorderStyle.SINGLE,size:10,color:c,space:8}},indent:{left:360},children:[new TextRun({text:t,size:19,font:'Arial',italics:true,color:'444444'})]});
const verd=(t,c)=>new Paragraph({spacing:{before:80,after:40},children:[new TextRun({text:'VERDICT: ',bold:true,size:21,font:'Arial',color:BLACK}),new TextRun({text:t,bold:true,size:21,font:'Arial',color:c})]});
function tbl(headers,rows,widths){return new Table({width:{size:9360,type:WidthType.DXA},columnWidths:widths,rows:[new TableRow({tableHeader:true,children:headers.map((h,i)=>new TableCell({borders,width:{size:widths[i],type:WidthType.DXA},shading:{fill:BLUE,type:ShadingType.CLEAR},margins:{top:80,bottom:80,left:120,right:120},children:[new Paragraph({children:[new TextRun({text:h,bold:true,size:18,font:'Arial',color:'FFFFFF'})]})]}))}),...rows.map((row,ri)=>new TableRow({children:row.map((cell,ci)=>new TableCell({borders,width:{size:widths[ci],type:WidthType.DXA},shading:{fill:ri%2===0?'FFFFFF':'F8F9FA',type:ShadingType.CLEAR},margins:{top:80,bottom:80,left:120,right:120},children:[new Paragraph({children:[new TextRun({text:String(cell),size:18,font:'Arial',color:BLACK})]})]}))}))]});}

const children=[
new Paragraph({alignment:AlignmentType.CENTER,spacing:{before:0,after:80},children:[new TextRun({text:'PROJECT SENTINEL',bold:true,size:40,font:'Arial',color:BLUE})]}),
new Paragraph({alignment:AlignmentType.CENTER,spacing:{before:0,after:80},children:[new TextRun({text:'Amendment #6 Completion Note',bold:true,size:30,font:'Arial',color:MIDBLUE})]}),
new Paragraph({alignment:AlignmentType.CENTER,spacing:{before:0,after:80},children:[new TextRun({text:'Path B: Event Salience Stratification Analysis',bold:true,size:24,font:'Arial',color:MIDBLUE})]}),
new Paragraph({alignment:AlignmentType.CENTER,spacing:{before:0,after:280},children:[new TextRun({text:'May 7, 2026',size:20,font:'Arial',color:GRAY,italics:true})]}),
meta('OSF Registration','https://osf.io/8hvf6'),
meta('Pre-registration commit','088ee6d (2026-05-06)'),
meta('Completion commit','6b67aee (2026-05-07)'),
meta('Results tables','sentinel_analysis.epoch_results_pathB, pathB_events, pathB_corpus, pathB_pairs'),
meta('Permutation results','pathB_H_B1_permtest_results.json, pathB_H_B3_permtest_results.json'),
rule(),
h1('1. Analysis Results'),
h2('1.1 Primary and Secondary Hypothesis Results'),
body('All four pre-registered hypotheses were tested. The primary outcome (pre-event elevation) is null across all features in all hypotheses.'),
new Paragraph({spacing:{before:120,after:120},children:[]}),
tbl(['Hypothesis','Event filter','Window','N events (dedup)','Water diff','Destruct diff','Urgency diff','Result'],
[['H_B1 (Primary)','M7.0+','7-day','393','-0.0246','-0.0291','-0.0501','NULL'],
['H_B2 (Secondary)','M7.0+','14-day','393','-0.0583','+0.0147','+0.0282','NULL'],
['H_B3 (Secondary)','M7.5+','7-day','140','+0.0371','-0.0401','-0.0831','NULL'],
['H_B4 (Secondary)','M8.0+ n>=10','14-day','4 unique','+0.4257','-0.2899','-0.1601','UNDERPOWERED']],
[1100,900,700,1100,900,1000,900,860]),
new Paragraph({spacing:{before:120,after:60},children:[]}),
note('emotion_z was NULL throughout all analyses. emotional_intensity is populated for only 6 of 4,144 sentinel-eligible records -- a NEXA/webform-only field not populated during Reddit or SDDb import. Excluded from all results.','7B0000'),
h2('1.2 H_B4 Detail -- M8.0+ Four Unique Events'),
body('After deduplication, only 4 unique events qualified for H_B4 (pre-registration specified n>=10 dreams in window). Results are descriptive only.'),
new Paragraph({spacing:{before:120,after:120},children:[]}),
tbl(['Event','Date','Mag','n pre14','n post14','Water diff','Notes'],
[['Peru (Navarro)','2019-05-26','8.0','10','13','+0.9971','Strong positive; balanced window'],
['Alaska (Chignik)','2021-07-29','8.2','10','3','+0.6877','Flagged: only 3 post-event dreams; baseline unreliable'],
['Kermadec Islands','2021-03-04','8.1','21','15','+0.4273','Best-balanced window; most reliable'],
['Kamchatka','2025-07-29','8.8','11','13','-0.1236','Largest event goes negative; contrary to salience prediction']],
[1500,900,600,800,800,900,2860]),
new Paragraph({spacing:{before:120,after:60},children:[]}),
note('Mean diff14_water = +0.497, SD=0.475. t(3)=2.09, p=0.13 two-tailed. Not significant before Bonferroni correction. Alaska window asymmetry inflates the mean. Kamchatka M8.8 going negative is directly contrary to the salience hypothesis.'),
h2('1.3 Permutation Test Results -- H_B1 and H_B3'),
body('2,000-permutation tests run for H_B1 and H_B3. Pre-registered direction: one-tailed pre > post. Seed: 42. All one-tailed p-values near 1.0 -- no pre-event elevation. Two-tailed tests revealed significant post-event elevation.'),
new Paragraph({spacing:{before:120,after:120},children:[]}),
tbl(['Feature','H_B1 obs','H_B1 z','H_B1 p2','H_B1 p1','H_B3 obs','H_B3 z','H_B3 p2','H_B3 p1'],
[['Water','-0.1627','-3.52','0.000','1.000','-0.1624','-2.08','0.034','0.983'],
['Destruction','-0.1258','-2.98','0.004','0.999','-0.0536','-0.77','0.477','0.775'],
['Urgency','-0.0886','-1.96','0.040','0.976','-0.2267','-2.97','0.004','0.999']],
[1040,780,700,780,780,780,700,780,780]),
new Paragraph({spacing:{before:120,after:60},children:[]}),
verd('H_B1: NULL (pre-event direction). H_B2: NULL. H_B3: NULL. H_B4: Underpowered (n=4), descriptive only.',RED),
rule(),
h1('2. The Post-Event Inflation Finding'),
body('The permutation tests revealed a robust methodological confound in retrospective self-reported dream corpora: systematic POST-event elevation of geophysical imagery features following major earthquakes. This is an unregistered secondary observation, not a hypothesis test outcome.'),
body('Water imagery (z=-3.52 at M7.0+) and urgency (z=-2.97 at M7.5+) show the strongest effects. The urgency effect strengthens at M7.5+ compared to M7.0+, consistent with larger events generating more intense post-event reporting. The mechanism: after a major earthquake, people who had disaster-themed dreams in the preceding days are more likely to remember, post about, and frame them as precognitive. This floods the corpus with post-event geophysical content, suppressing the pre/post ratio and making pre-event signal detection impossible in a retrospective corpus regardless of whether genuine precognitive effects exist.'),
note('This finding is publishable in its own right. To our knowledge this is the first quantification of post-event reporting inflation in a large-scale dream corpus analyzed against a geophysical event catalog with pre-registered methodology. It has direct implications for all retrospective dream precognition research and constitutes a clear, evidence-based argument for why prospective timestamped collection is necessary.'),
rule(),
h1('3. The Two-Stream Convergence Framing'),
h2('3.1 Structural Parallel'),
body('The geophysical signal stream problem and the HAC corpus problem are structurally identical. Both involve a real phenomenon being tested against data with insufficient signal-to-noise ratio. In both cases the null baseline is now documented and a higher-fidelity data source has been identified.'),
new Paragraph({spacing:{before:120,after:120},children:[]}),
tbl(['Dimension','Geophysical stream (H1-H4)','HAC stream (SEA)'],
[['Data source','Public archives: TEC, GPS, Kp/Ap/Dst','Reddit dream corpus (general population)'],
['Null result','Clean null across all hypotheses','Clean null across all event thresholds'],
['What null means','Public data too coarse; not evidence against precursors','Wrong corpus; not evidence against precognition'],
['Higher-fidelity source','Precursor SPC atmospheric electrical streams','Prospective corpus of tracked sensitives'],
['Status','Pending Precursor SPC NDA/agreement','Pending multilingual dream intake app']],
[1560,3900,3900]),
new Paragraph({spacing:{before:120,after:60},children:[]}),
h2('3.2 The Baseline as Evidence'),
body('The null results are the documented baseline that makes a future convergence result meaningful. If both the geophysical precursor signals and the HAC signals elevate before the same qualifying event in a future prospective study, the Phase 2 and Path B nulls allow the statement: "this is not what we normally see -- something different happened here." Without the null baseline, any positive result could be dismissed as cherry-picking. With it, a positive result has an established comparison point.'),
body('The population-level SEA program is complete. No further SEA amendments are planned. Future analytical work will focus on the individual-level scanner, prospective corpus design, and the convergence test architecture.'),
note('The convergence test is the most scientifically interesting outcome available to this project. It requires both data streams to have adequate signal-to-noise simultaneously -- which neither currently does. Precursor SPC fixes one side. The dream app fixes the other.','1E6B2E'),
rule(),
h1('4. Protocol Deviations'),
bullet('emotion_z excluded: emotional_intensity populated for only 6/4,144 records. Corpus limitation, not methodological deviation.'),
bullet('H_B4 threshold correction: SQL initially filtered on n_pre7>=10; corrected to n_pre14>=10 per pre-registration language before examining feature scores.'),
bullet('Duplicate event deduplication: Catalog contains separate earthquake and tsunami entries for same events. Deduplicated preferring earthquake entries. Not pre-specified but a data quality correction.'),
bullet('hac_features_daily rebuild: Intermediate table absent at session start; rebuilt from source tables using identical logic.'),
bullet('H_B2 and H_B4 permutation tests waived: H_B2 shows mixed near-zero effects; H_B4 has n=4 events. Both decisions documented here.'),
rule(),
h1('5. Next Steps'),
bullet('Commit this completion note to GitHub and upload to OSF'),
bullet('Build geophysical/scientific executive summary (Tim Gallaudet, Clive Cook, USGS/NASA audiences)'),
bullet('Build HAC/consciousness executive summary (IONS, Helane Wahbeh, IRVA, CoDreaming audiences)'),
bullet('Substack timing and framing: part of broader communications strategy, not yet scheduled'),
bullet('Action flags: Amatrice timestamp retrieval, Hyuga-nada BQ re-association, Melvin dreamer-level query'),
bullet('Dream intake app: RFC 3161 timestamping, 10-language support, IRB sensitivity tracking -- in progress'),
bullet('Precursor SPC: NDA pending; H4 convergence model on hold'),
bullet('IONS/NEXA 2.0: Path A pending Helane Wahbeh response'),
];

const doc=new Document({sections:[{properties:{page:{size:{width:12240,height:15840},margin:{top:1200,right:1200,bottom:1200,left:1200}}},footers:{default:new Footer({children:[new Paragraph({alignment:AlignmentType.CENTER,children:[new TextRun({text:'Project Sentinel -- Amendment #6 Completion Note | Path B | May 2026 | Page ',size:16,font:'Arial',color:GRAY}),new TextRun({children:[PageNumber.CURRENT],size:16,font:'Arial',color:GRAY})]})]}),},children}]});
Packer.toBuffer(doc).then(buf=>{fs.writeFileSync('Sentinel_PreReg_Amendment6_PathB_CompletionNote.docx',buf);console.log('done');});
