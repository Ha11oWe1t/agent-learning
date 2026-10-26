// Static learning guidance, independent of the model and private scenario facts.
const STAGE_GUIDES = {
  '1': {
    title:'需求澄清', goal:'把模糊诉求变成有边界、有依据、能验收的业务需求。你负责提问，需求方负责确认。',
    availability:'当前可练习：访谈 → 记录笔记 → 生成需求文档。',
    items:[
      {title:'目标与用户', tasks:['确定谁使用、在哪里使用，以及当前的处理流程。','问清具体痛点和业务目标，区分必要目标与期望收益。'], question:'这个助手主要给谁使用？他们现在怎么处理这件事，最希望改善哪个问题？'},
      {title:'范围与边界', tasks:['明确第一期必须做、暂不做和禁止自动执行的事项。','把“智能诊断”“自动处理”等说法拆成具体动作。'], question:'第一期必须完成哪些事情？哪些操作只能提供建议，哪些必须由人决定？'},
      {title:'流程与确认', tasks:['逐步梳理输入、处理、输出和结束条件。','明确缺信息时如何追问、何时由用户确认，以及重复操作怎么处理。'], question:'能用一个典型案例，从用户提出问题到任务结束走一遍吗？哪些步骤需要确认？'},
      {title:'数据与依赖', tasks:['明确需要哪些文档、业务数据和接口，谁提供、能否授权使用。','确认数据版本、更新责任人及冲突时以什么为准。'], question:'这些资料和数据现在在哪里、由谁维护？如果版本冲突或接口暂时拿不到，应该怎么办？'},
      {title:'权限与异常', tasks:['问清谁能访问什么、谁能提交或修改，以及人工接管条件。','覆盖资料缺失、接口失败、结论不确定和重复提交的业务处理方式。'], question:'哪些用户可以查看或修改这些信息？当查不到依据、接口失败或拿不准时，应该怎样处理？'},
      {title:'验收标准', tasks:['定义什么叫任务成功，准备可以检查的案例与预期结果。','区分普通效果指标与绝对不能出现的错误；未约定的数字保留待确认。'], question:'你们准备怎样验收？能给出几条成功和失败的例子吗？哪些错误一次都不能发生？'},
      {title:'排期与约束', tasks:['确认试点范围、上线时间、成本、网络和部署约束。','把尚未确定的问题记下，明确找谁确认、何时确认。'], question:'希望何时让哪些人试用？预算、网络或部署有哪些限制？未定事项由谁确认？'},
    ],
    deliverables:['一页需求说明：目标、用户、范围和业务流程。','需求细节：已确认事实、待确认事项、冲突及各自来源。','验收案例、依赖负责人和后续追问清单。'],
    done:'另一位开发人员能据此说明系统应该做什么、不能做什么、怎样算成功；未决问题有负责人，不用猜测填补。',
    reminder:'问过不等于确认过。把需求方明确承诺、自己的设想和待核实内容分开；这里的提示不是当前场景的标准答案。',
  },
  '3': {
    title:'技术方案设计', goal:'把已澄清的业务需求转换成可实现、可验证的系统设计，并解释关键选择。',
    availability:'当前可练习：选择定稿需求 → 搭流程与配置节点 → 技术负责人评审 → 修改并导出方案。',
    items:[
      {title:'输入需求与关键约束', tasks:['从需求文档列出必须覆盖的业务流程与验收条件。','标出仍未确认、会影响架构的依赖；暂定方案要写清假设。'], question:'这份方案解决哪些已确认需求？哪些假设如果改变，会影响设计？'},
      {title:'模型与程序分工', tasks:['将语言理解、检索、业务规则、权限和写入动作分开。','为固定流程、自主决策和多 Agent 分工说明理由。'], question:'每一步由模型、普通代码、工具还是人工负责？为什么这样分工？'},
      {title:'工作流与状态', tasks:['画出正常路径、信息不足、失败、转人工和结束路径。','定义节点输入输出、共享状态、更新规则及循环上限。'], question:'用户中途换了设备或订单，哪些状态要清除？流程在哪些条件下继续、重试或结束？'},
      {title:'知识与工具接口', tasks:['设计资料切分、检索、适用性过滤和来源引用。','定义工具参数、返回结构、鉴权、超时、幂等和错误格式。'], question:'哪些信息从资料中检索，哪些必须查实时接口？如何保证工具参数与资料版本适用？'},
      {title:'上下文与持久化', tasks:['确定对话记忆、业务状态和文档版本分别保存在哪里。','明确刷新、重启和并发请求时如何恢复，防止重复写入。'], question:'服务重启后要恢复什么？对话历史和业务状态谁是唯一可信的数据源？'},
      {title:'异常与人工介入', tasks:['把权限校验、操作确认和高风险业务规则落到明确位置。','设计服务不可用、模型输出无效、数据冲突与人工接管。'], question:'模型或接口失败时系统怎样退回到可恢复状态？哪些操作必须人工确认？'},
      {title:'验证与方案取舍', tasks:['比较效果、延迟、费用、实现难度和维护成本。','列出最不确定的部分、验证方法和可分步实施的任务。'], question:'如何证明这套设计满足验收条件？最先需要用原型验证哪个风险？'},
    ],
    deliverables:['架构图与带异常分支的工作流图。','状态定义、接口约定及知识检索方案。','技术取舍、验证计划、依赖和开发任务拆分。'],
    done:'开发人员能按模块开始实现；关键需求都有负责模块和验证方法，失败路径及未确定的假设都写清楚。',
    reminder:'方案要能落地和验证。多 Agent、记忆、微调等能力都应有明确需求依据，不按技术名词数量判断方案好坏。',
  },
  '5': {
    title:'智能体开发', goal:'按方案做出可端到端运行的系统，确保关键行为正确、失败可定位、成果可复现。',
    availability:'指南可查看；本阶段的交互练习功能后续开放。',
    items:[
      {title:'工程骨架与配置', tasks:['组织目录、依赖、启动方式和环境配置。','分离密钥与代码，先用模拟数据或服务建立开发环境。'], question:'其他人怎样启动这个项目？缺少密钥或外部服务时能否明确提示？'},
      {title:'最小完整流程', tasks:['先打通输入、一次模型决策、一次工具调用和结果展示。','逐步增加能力，每次保持一条可以演示的完整业务路径。'], question:'最小版本能让用户从开始到结束完成哪一件事？'},
      {title:'工具与数据校验', tasks:['实现真实接口或明确标注的模拟接口，校验输入与返回结构。','在程序中执行身份权限、确定性规则和重复提交保护。'], question:'参数缺失、返回格式异常、权限不符或重复点击时，工具会怎样处理？'},
      {title:'Agent 与流程编排', tasks:['实现角色提示词、节点、路由和上下文传递。','限制调用轮数；校验模型输出，禁止把工具失败写成成功。'], question:'每个节点读写什么？什么条件触发下一步，怎样避免循环或误报执行成功？'},
      {title:'状态、交互与持久化', tasks:['接好 WebUI 的加载、失败、确认和恢复状态。','保存对话、笔记和版本；处理刷新与同时提交时的数据一致性。'], question:'用户等待时、刷新后或请求失败后，会看到什么？已保存和未保存内容能否区分？'},
      {title:'开发自测与排错', tasks:['给关键行为编写测试，覆盖正常、缺信息、异常和越权路径。','记录必要的检索、参数与执行结果，用日志定位问题且不泄露密钥。'], question:'如何重现并定位这个失败？修复后，哪条回归测试证明问题没有再出现？'},
      {title:'阶段性交付', tasks:['整理运行说明、配置示例、接口说明和已知问题。','对照需求逐项检查，列出进入评测与优化阶段仍需验证的内容。'], question:'别人不依赖你的口头指导能否启动并操作？哪些能力已验证，哪些仍需后续评测？'},
    ],
    deliverables:['可运行的代码、WebUI 和业务接口。','关键路径的测试、日志与可复现的演示案例。','启动说明、配置模板及已知问题清单。'],
    done:'完整业务流程可运行，关键异常可处理且能定位；他人能按说明复现，为后续系统评测与优化做好准备。',
    reminder:'一次演示成功不等于完成验收。开发自测通过后，仍需经过第 6 阶段的系统评测与优化。',
  },
};

(() => {
  const dialog=document.getElementById('stage-guide');
  const content=document.getElementById('guide-content');
  const buttons=[...document.querySelectorAll('[data-guide-tab]')];
  function node(tag,cls,text){const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;}
  function select(stage){
    const guide=STAGE_GUIDES[stage];
    document.getElementById('guide-heading').textContent=`${stage.padStart(2,'0')} · ${guide.title}`;
    document.getElementById('guide-goal').textContent=guide.goal;
    document.getElementById('guide-availability').textContent=guide.availability;
    buttons.forEach(b=>{const selected=b.dataset.guideTab===stage;b.setAttribute('aria-selected',String(selected));b.tabIndex=selected?0:-1;});
    content.setAttribute('aria-labelledby','guide-tab-'+stage);
    content.replaceChildren(node('h3','','这个阶段要做什么'));
    guide.items.forEach((item,index)=>{
      const details=document.createElement('details');details.className='guide-item';details.open=index===0;
      details.append(node('summary','',`${index+1}. ${item.title}`));
      const list=document.createElement('ul');item.tasks.forEach(task=>list.append(node('li','',task)));details.append(list);
      details.append(node('p','guide-question',(stage==='1'?'可以这样问需求方：':'设计或实现时问自己：')+item.question));
      content.append(details);
    });
    content.append(node('h3','','建议交付物'));const list=document.createElement('ul');list.className='guide-deliverables';guide.deliverables.forEach(item=>list.append(node('li','',item)));content.append(list);
    content.append(node('h3','','什么时候可以进入下一阶段'),node('p','guide-done',guide.done),node('p','guide-reminder',guide.reminder));
    content.scrollTop=0;
  }
  document.querySelectorAll('[data-stage-guide]').forEach(button=>button.addEventListener('click',()=>{select(button.dataset.stageGuide);dialog.showModal();}));
  buttons.forEach((button,index)=>{
    button.addEventListener('click',()=>select(button.dataset.guideTab));
    button.addEventListener('keydown',event=>{
      let next;if(event.key==='ArrowRight')next=(index+1)%buttons.length;else if(event.key==='ArrowLeft')next=(index+buttons.length-1)%buttons.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=buttons.length-1;else return;
      event.preventDefault();select(buttons[next].dataset.guideTab);buttons[next].focus();
    });
  });
  document.getElementById('guide-close').addEventListener('click',()=>dialog.close());
})();
