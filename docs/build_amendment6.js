const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, AlignmentType, BorderStyle, WidthType, ShadingType, Footer, PageNumber } = require('docx');
const fs = require('fs');
const BLUE='1F3864', MIDBLUE='2E5F9E', GOLD='7D6608', BLACK='000000', GRAY='888888';
const border={style:BorderStyle.SINGLE,size:1,color:'CCCCCC'};
const borders={top:border,bottom:border,left:border,right:border};
const rule=()=>new Paragraph({spacing:{before:160,after:160},border:{bottom:{style:BorderStyle.SINGLE,size:4,color:'DDDDDD',space:1}},children:[new TextRun('')]});
const h1=(t)=>new Paragraph({spacing:{before:320,after:120},children:[new TextRun({text:t,bold:true,size:28,color:BLUE,font:'Arial'})]});
const h2=(t)=>new Paragraph({spacing:{before:200,after:80},children:[new TextRun({text:t,bold:true,size:24,color:MIDBLUE,font:'Arial'})]});
const body=(t)=>new Paragraph({spacing:{before:60,after:60},children:[new TextRun({text:t,size:20,font:'Arial',color:BLACK})]});
const bullet=(t)=>new Paragraph({spacing:{before:40,after:40},indent:{left:360},children:[new TextRun({text:'• '+t,size:20,font:'Arial',color:BLACK})]});
const meta=(l,v)=>new Paragraph({spacing:{before:40,after:40},children:[new TextRun({text:l+': ',bold:true,size:19,font:'Arial',color:MIDBLUE}),new TextRun({text:v,size:19,font:'Arial',color:BLACK})]});
const note=(t)=>new Paragraph({spacing:{before:60,after:60},shading:{fill:'F5F5F5',type:ShadingType.CLEAR},border:{left:{style:BorderStyle.SINGLE,size:8,color:GOLD,space:8}},indent:{left:360},children:[new TextRun({text:t,size:19,font:'Arial',italics:true,color:'555555'})]});
function makeTable(headers,rows,widths){return new Table({width:{size:9360,type:WidthType.DXA},columnWidths:widths,rows:[new TableRow({tableHeader:true,children:headers.map((h,i)=>new TableCell({borders,width:{size:widths[i],type:WidthType.DXA},shading:{fill:BLUE,type:ShadingType.CLEAR},margins:{top:80,bottom:80,left:120,right:120},children:[new Paragraph({children:[new TextRun({text:h,bold:true,size:18,font:'Arial',color:'FFFFFF'})]})]}))}),...rows.map((row,ri)=>new TableRow({children:row.map((cell,ci)=>new TableCell({borders,width:{size:widths[ci],type:WidthType.DXA},shading:{fill:ri%2===0?'FFFFFF':'F8F9FA',type:ShadingType.CLEAR},margins:{top:80,bottom:80,left:120,right:120},children:[new Paragraph({children:[new TextRun({text:String(cell),size:18,font:'Arial',color:BLACK})]})]}))}))]});}
const children=[
  new Paragraph({alignment:AlignmentType.CENTER,spacing:{before:0,after:80},children:[new TextRun({text:'PROJECT SENTINEL',bold:true,size:40,font:'Arial',color:BLUE})]}),
  new Paragraph({alignment:AlignmentType.CENTER,spacing:{before:0,after:80},children:[new TextRun({text:'Pre-Registration Amendment #6',bold:true,size:30,font:'Arial',color:MIDBLUE})]}),
  new Paragraph({alignment:AlignmentType.CENTER,spacing:{before:0,after:80},children:[new TextRun({text:'Path B: Event Salience Stratification Analysis',bold:true,size:26,font:'Arial',color:MIDBLUE})]}),
  new Paragraph({alignment:AlignmentType.CENTER,spacing:{before:0,after:280},children:[new TextRun({text:'Filed prior to analysis execution | May 6, 2026',size:20,font:'Arial',color:GRAY,italics:true})]}),
  meta('OSF Registration','https://osf.io/8hvf6'),
  meta('Filing date','2026-05-06'),
  meta('Status','Pre-registered -- no feature data examined prior to this filing'),
  meta('Supersedes','Amendment #5 (within-source normalization, geophysical_imagery deprecation)'),
  meta('GitHub commit','088ee6d'),
  rule(),
  h1('1. Motivation'),
  body('Phase 2 superposed epoch analysis returned a clean null across all corpus permutations tested in Amendments #1-5. That null stands. However Phase 2 treated all M6+ events as equivalent -- a scientifically unjustified assumption.'),
  body('The Dunne (1927) hypothesis predicts that high-salience events should generate stronger pre-event dream signal because the dreamer\'s future emotional experience of watching a M8.0 disaster is qualitatively different from their future experience of reading a brief wire story about a minor tremor. Amendment #6 tests this prediction directly.'),
  rule(),
  h1('2. Pre-Registered Hypotheses'),
  h2('H_B1 -- Primary'),
  body('Mean normalized feature score in the -7 to -1 day pre-event window is significantly higher than the post-event baseline (+1 to +7 days) for M7.0+ earthquake and tsunami events.'),
  body('Features: water_imagery, destruction_imagery, high_urgency, high_emotion. Within-source normalization from Amendment #5. Event filter: hazard IN (earthquake, tsunami) AND mag >= 7.0. Statistical test: two-tailed t-test or Wilcoxon, 2,000-permutation validation, alpha = 0.05.'),
  h2('H_B2 -- Secondary A: Extended Window'),
  body('Same as H_B1, extended pre-event window -14 to -1 days. Enables direct comparison with Phase 2 protocol.'),
  h2('H_B3 -- Secondary B: M7.5+ Only'),
  body('Same as H_B1, restricted to M7.5+ events. Tests whether higher magnitude events generate stronger pre-event signal.'),
  h2('H_B4 -- Secondary C: M8.0+ Adequately Covered'),
  body('Same as H_B1, restricted to M8.0+ events with >=10 dreams in the +/-14 day window (n=14 events). Non-parametric test. Bonferroni correction: alpha = 0.0167 across all secondary analyses.'),
  h2('Exploratory Only -- M8.0+ Long-Lead Window'),
  note('EXPLORATORY ONLY. No hypothesis test. No p-values. Descriptive visualization only. Motivated by Tohoku NEXA case (cbf61709) where credible dream occurred approximately 90-120 days before the M9.0 event. Window: -90 to +14 days for the 14 adequately-covered M8.0+ events.'),
  rule(),
  h1('3. Event Catalog'),
  meta('Source','synexis-project-sentinel.sentinel_groundtruth.events'),
  meta('Criteria','hazard IN (earthquake, tsunami) AND mag >= 7.0 AND start_ts IS NOT NULL'),
  body('Pre-analysis coverage characterization (COUNT query only -- no feature data examined):'),
  new Paragraph({spacing:{before:120,after:120},children:[]}),
  makeTable(['Magnitude band','N events','Mean dreams/window','Events with >=10 dreams'],[['M8.0+','57','7.1','14'],['M7.5-7.9','180','10.5','76'],['M7.0-7.4','354','10.6','152']],[2340,1560,2340,3120]),
  new Paragraph({spacing:{before:120,after:60},children:[]}),
  note('M8.0+ events have lower corpus coverage because many predate the Reddit corpus (2012+). H_B4 restricts to the 14 adequately-covered M8.0+ events.'),
  rule(),
  h1('4. Dream Corpus'),
  meta('Source','synexis-project-sentinel.hac_intake.hac_normalized'),
  meta('Eligibility','is_sentinel_eligible=TRUE, experience_date IS NOT NULL, is_duplicate=FALSE'),
  meta('Normalization','Within-source z-score normalization (Amendment #5)'),
  body('Date confidence weighting:'),
  bullet('high or medium confidence: weight = 1.0'),
  bullet('low, unknown, or NULL confidence: weight = 0.5'),
  rule(),
  h1('5. Analysis Protocol'),
  h2('5.1 Primary Analysis (H_B1)'),
  body('For each M7.0+ qualifying event: pull dreams in pre-event window [-7,-1] and post-event window [+1,+7]. Compute mean within-source normalized feature score per window. Test whether pre-post difference distribution is significantly positive. Validate with 2,000-permutation test using randomly shuffled event dates.'),
  h2('5.2 Secondary Analyses (H_B2, H_B3, H_B4)'),
  body('Same protocol with modified filters and/or windows as specified in Section 2. Bonferroni correction: alpha = 0.0167.'),
  h2('5.3 Exploratory M8.0+ Long-Lead'),
  body('For 14 adequately-covered M8.0+ events: compute mean feature score by day across -90 to +14 day window. Visualize only. No statistical inference.'),
  rule(),
  h1('6. Outcome Reporting'),
  body('Results reported regardless of direction. A null result is meaningful and will be fully reported. Effect sizes and confidence intervals reported alongside p-values for all outcomes.'),
  rule(),
  h1('7. What This Analysis Cannot Establish'),
  body('A positive result is consistent with the Dunne salience hypothesis but does not confirm it. Alternative explanations include corpus composition artifacts, retrospective reporting inflation, and multiple comparison issues. Independent prospective replication required before causal interpretation. The multilingual dream intake app under development is the intended prospective replication instrument.'),
  rule(),
  h1('8. Infrastructure'),
  meta('Analysis script','~/epoch_pathB.sql (built after pre-registration commit)'),
  meta('Results table','sentinel_analysis.epoch_results_pathB'),
  meta('Walk-forward validation','Same permutation engine as Amendment #5'),
  note('This amendment is filed prior to any analysis execution. Amendment #5 null results stand and are unaffected.'),
];
const doc=new Document({sections:[{properties:{page:{size:{width:12240,height:15840},margin:{top:1200,right:1200,bottom:1200,left:1200}}},footers:{default:new Footer({children:[new Paragraph({alignment:AlignmentType.CENTER,children:[new TextRun({text:'Project Sentinel -- Pre-Registration Amendment #6 | Path B | May 2026 | Page ',size:16,font:'Arial',color:GRAY}),new TextRun({children:[PageNumber.CURRENT],size:16,font:'Arial',color:GRAY})]})]}),},children}]});
Packer.toBuffer(doc).then(buf=>{fs.writeFileSync('/home/synexisproject/project-sentinel/docs/Sentinel_PreReg_Amendment6_PathB.docx',buf);console.log('done');});
