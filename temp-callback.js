// 全局校验回调
function validate() {
    var role = getFieldValue("role"); // 获取角色字段值
    var empName = getFieldValue("emp_name"); // 获取姓名字段值
    
    // 角色为必填
    if (!role || role === "") {
        showMessage("请选择角色");
        return false;
    }
    
    // 姓名必填
    if (!empName || empName === "") {
        showMessage("请输入姓名");
        return false;
    }
    
    // 董事长和经理需要填写部门
    if (role === "董事长" || role === "经理") {
        var deptId = getFieldValue("dept_id");
        if (!deptId || deptId === "") {
            showMessage("董事长和经理必须选择部门");
            return false;
        }
    }
    
    return true;
}

// 表单提交前校验
function beforeSave() {
    return validate();
}

// 页面加载完成
function onLoad() {
    // 默认选中角色字段
    setFieldRequired("role", true);
    setFieldRequired("emp_name", true);
}