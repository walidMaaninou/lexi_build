import streamlit as st
import pandas as pd
import re
import io

st.set_page_config(layout="wide")

st.markdown("""
    <style>
        html, body, [class^="css"] {
            direction: rtl;
            text-align: right;
        }
    </style>
""", unsafe_allow_html=True)


# === Helper Functions ===

def generate_next_id(hierarchy):
    numeric_ids = []
    for eid in hierarchy:
        match = re.search(r"([a-zA-Z]+)-(\d+)", eid)
        if match:
            prefix, number = match.groups()
            numeric_ids.append((prefix, int(number)))
    if numeric_ids:
        max_prefix, max_number = max(numeric_ids, key=lambda x: x[1])
        return f"{max_prefix}-{max_number + 1}"
    else:
        return "z-1"

def load_csv(uploaded_file):
    df = pd.read_excel(uploaded_file)
    return df

def build_hierarchy_from_outline(df):
    hierarchy = {}
    id_counter = 1
    node_stack = {}  # Track last seen node at each level

    type_map = {
        0: "باب رئيس",  # Top-level category
        1: "فصل",       # Section
        2: "موضوع",     # Topic
        3: "مدخل",      # Entry
    }

    for _, row in df.iterrows():
        for col_idx, cell in enumerate(row):
            if pd.notna(cell) and isinstance(cell, str) and len(cell.strip()) > 0:
                node_name = cell.strip()

                # Try to get a definition from the next column
                definition = ""
                if col_idx + 1 < len(row) and isinstance(row[col_idx + 1], str):
                    definition = row[col_idx + 1].strip()

                node_id = f"N{id_counter}"
                id_counter += 1

                # Determine parent: the closest node in a previous column
                parents = []
                for i in reversed(range(col_idx)):
                    if i in node_stack:
                        parents = [node_stack[i]]
                        break
                
                # Assign the type based on column index
                node_type = type_map.get(col_idx, "غير معروف")

                # Add node to hierarchy
                hierarchy[node_id] = {
                    "name": node_name,
                    "type": node_type,
                    "definition": definition,
                    "parents": parents,
                    "children": [],
                }

                # Add this node to the stack at its level
                node_stack[col_idx] = node_id

    # Add children references
    for eid, data in hierarchy.items():
        for pid in data["parents"]:
            if pid in hierarchy:
                hierarchy[pid]["children"].append(eid)

    return hierarchy

def build_hierarchy(df):
    hierarchy = {}
    for _, row in df.iterrows():
        element_id = str(row["الرقم التعريفي"]) # Ensure ID is string for consistent keys
        parent_ids = [str(row[col]) for col in df.columns if col.startswith("علاقة جزء من كل") and pd.notna(row[col])]
        hierarchy[element_id] = {
            "name": row["المدخل"],
            "type": row["النوع"],
            "definition": row.get("الشرح", ""),
            "parents": parent_ids,
            "children": [],
        }

    # Assign children
    for eid, data in hierarchy.items():
        for parent in data["parents"]:
            if parent in hierarchy:
                hierarchy[parent]["children"].append(eid)
    return hierarchy

def get_siblings(hierarchy, element_id):
    element = hierarchy[element_id]
    siblings = set()
    for parent_id in element["parents"]:
        siblings.update(hierarchy[parent_id]["children"])
    siblings.discard(element_id)
    return list(siblings)

def add_element(hierarchy, new_id, name, type_, definition, parent_id):
    if new_id in hierarchy:
        st.warning("هذا الرقم التعريفي موجود مسبقًا.")
        return
    hierarchy[new_id] = {
        "name": name,
        "type": type_,
        "definition": definition,
        "parents": [parent_id] if parent_id else [],
        "children": [],
    }
    if parent_id and parent_id in hierarchy:
        hierarchy[parent_id]["children"].append(new_id)

def export_to_csv(hierarchy):
    rows = []
    max_parents = 0
    if "hierarchy" in st.session_state and st.session_state["hierarchy"]:
        max_parents = max(len(data["parents"]) for data in st.session_state["hierarchy"].values())

    all_parent_cols = [f"علاقة جزء من كل {i+1}" for i in range(max_parents)]
    
    base_cols = ["الرقم التعريفي", "المدخل", "الشرح", "النوع"]
    final_cols = base_cols + [col for col in all_parent_cols if col not in base_cols]

    for eid, data in hierarchy.items():
        row = {
            "الرقم التعريفي": eid,
            "المدخل": data["name"],
            "الشرح": data["definition"],
            "النوع": data["type"],
        }
        for col in all_parent_cols:
            row[col] = None

        for i, parent in enumerate(data["parents"]):
            if i < max_parents:
                row[f"علاقة جزء من كل {i+1}"] = parent
        rows.append(row)
        
    return pd.DataFrame(rows, columns=final_cols)

# RTL Subheader Helper
def rtl_subheader(text):
    st.markdown(f"<h3 style='text-align: center; direction: rtl'>{text}</h3>", unsafe_allow_html=True)

# Helper to get automatic type based on context
def infer_type(context, current_type):
    child_map = {
        "باب رئيسي": "فصل",
        "فصل": "موضوع",
        "موضوع": "مدخل"
    }
    parent_map = {
        "مدخل": "موضوع",
        "موضوع": "فصل",
        "فصل": "باب رئيسي"
    }

    if context == "child":
        return child_map.get(current_type, "مدخل")
    elif context == "parent":
        return parent_map.get(current_type, "باب رئيسي")
    elif context == "sibling":
        return current_type
    return "مدخل"

# UI section to add new elements in context
def render_add_form(context_label, parent_id, auto_type, form_key_suffix):

    # Arabic label based on inferred type
    type_labels = {
        "مدخل": "مدخل",
        "موضوع": "موضوع",
        "فصل": "فصل",
        "عنصر": "عنصر",
    }

    type_icons = {
        "مدخل": "🟡",  # Yellow
        "موضوع": "🟠",  # Orange
        "فصل": "🔴",   # Red
    }
    icon = type_icons.get(auto_type, "📁")

    context_label = type_labels.get(auto_type, auto_type)

    unique_form_key = f"add_form_{context_label}_{form_key_suffix}"
    with st.expander(f"➕ إضافة عنصر ك{context_label} {icon}", expanded=False):

        with st.form(unique_form_key):
            new_id = generate_next_id(st.session_state["hierarchy"])
            new_name = st.text_input("🏷️ الاسم", key=f"name_{unique_form_key}")
            # st.markdown(f"<p style='text-align: right; direction: rtl'><strong>📌 الرقم التعريفي:</strong> {new_id}</p>", unsafe_allow_html=True)
            st.markdown(f"<p style='text-align: right; direction: rtl'><strong>📂 النوع:</strong> {auto_type}</p>", unsafe_allow_html=True)
            st.markdown(
                f"<p style='text-align: right; direction: rtl'>"
                f"<strong>📌 سيتم الإضافة إلى:</strong> {st.session_state["hierarchy"][parent_id]["name"]}</p>",
                unsafe_allow_html=True
            )

            new_def = ""
            if auto_type == "مدخل":
                new_def = st.text_area("📖 الشرح", key=f"def_{unique_form_key}")

            submitted = st.form_submit_button("إضافة")
            if submitted:
                add_element(st.session_state["hierarchy"], new_id, new_name, auto_type, new_def, parent_id)
                st.session_state.show_add_success = True
                st.rerun()
                
# UI for adding multiple 'مدخل' elements at once
def render_batch_madkhal_form(parent_id, form_key_suffix):
    unique_form_key = f"batch_add_madkhal_form_{form_key_suffix}"
    with st.expander("➕ إضافة مداخل متعددة", expanded=False):
        with st.form(unique_form_key):
            st.markdown("👥 أدخل أسماء المداخل كل اسم في سطر منفصل:")
            names_input = st.text_area("✍️ أسماء المداخل", key=f"batch_names_{unique_form_key}")

            st.markdown(
                f"<p style='text-align: right; direction: rtl'>"
                f"<strong>📂 النوع:</strong> مدخل</p>",
                unsafe_allow_html=True
            )
            st.markdown(
                f"<p style='text-align: right; direction: rtl'>"
                f"<strong>📌 سيتم الإضافة إلى:</strong> {st.session_state["hierarchy"][parent_id]["name"]}</p>",
                unsafe_allow_html=True
            )

            submitted = st.form_submit_button("إضافة الكل")
            if submitted:
                names = [name.strip() for name in names_input.split("\n") if name.strip()]
                for name in names:
                    new_id = generate_next_id(st.session_state["hierarchy"])
                    add_element(
                        st.session_state["hierarchy"],
                        new_id,
                        name.split(":", 1)[0],
                        "مدخل",
                        name,  # or use a default definition or leave empty
                        parent_id
                    )
                st.success(f"تمت إضافة {len(names)} مدخل.")
                st.rerun()

if "show_add_success" in st.session_state and st.session_state.show_add_success:
    st.toast("تم إضافة العنصر الجديد ✅", icon="➕")
    st.session_state.show_add_success = False  # reset

if "show_edit_success" in st.session_state and st.session_state.show_edit_success:
    st.toast("تم تعديل العنصر بنجاح ✅", icon="✏️")
    st.session_state.show_edit_success = False  # reset

if "show_delete_success" in st.session_state and st.session_state.show_delete_success:
    st.toast("تم حذف العنصر بنجاح ✅", icon="🗑️")
    st.session_state.show_delete_success = False  # reset



# === Streamlit UI ===
st.markdown(f"<h2 style='text-align: right; direction: rtl'>{"🧱 بناء وتصفح التسلسل الهرمي للمفاهيم"}</h2>", unsafe_allow_html=True)

# # File Upload
# uploaded_file = st.sidebar.file_uploader("📤 تحميل ملف CSV", type=["xlsx", "tsv"])
# if uploaded_file and "hierarchy" not in st.session_state:
#     df = load_csv(uploaded_file)
#     hierarchy = build_hierarchy(df)
#     st.session_state["hierarchy"] = hierarchy
#     st.session_state["uploaded_filename"] = uploaded_file.name
#     st.session_state["current_id"] = next((eid for eid, d in hierarchy.items() if not d["parents"]), None)
#     st.toast("✅ تم تحميل الملف بنجاح!", icon="📁")

st.sidebar.markdown("### 🚀 ابدأ مشروعك")

# Option to start new project or import existing
project_choice = st.sidebar.radio(
    "اختر طريقة البدء:",
    ["📂 تحميل ملف موجود", "🆕 بدء مشروع جديد"]
)

# Handle new project start
if project_choice == "🆕 بدء مشروع جديد" and "hierarchy" not in st.session_state:
    with st.sidebar.form("new_project_form"):
        root_name = st.text_input("📌 اسم الباب الرئيسي", value="باب رئيسي")
        submitted = st.form_submit_button("ابدأ المشروع")
        if submitted:
            new_id = "br-1"  # default starting ID
            st.session_state["hierarchy"] = {
                new_id: {
                    "name": root_name,
                    "type": "باب رئيسي",
                    "definition": "",
                    "parents": [],
                    "children": [],
                }
            }
            st.session_state["current_id"] = new_id
            st.toast("✅ تم بدء مشروع جديد!", icon="🆕")
            st.rerun()

# Handle file upload if selected
if project_choice == "📂 تحميل ملف موجود":
    uploaded_file = st.sidebar.file_uploader("📤 تحميل ملف Excel", type=["xlsx"])
    if uploaded_file and "hierarchy" not in st.session_state:
        df = load_csv(uploaded_file)
        try:
            hierarchy = build_hierarchy(df)
        except:
            df = pd.read_excel(uploaded_file, header=None)
            hierarchy = build_hierarchy_from_outline(df)
        st.session_state["hierarchy"] = hierarchy
        st.session_state["uploaded_filename"] = uploaded_file.name
        st.session_state["current_id"] = next((eid for eid, d in hierarchy.items() if not d["parents"]), None)
        st.toast("✅ تم تحميل الملف بنجاح!", icon="📁")
        st.rerun()

if "hierarchy" in st.session_state:
    hierarchy = st.session_state["hierarchy"]
    current_id = st.session_state["current_id"]
    current = hierarchy[current_id]

    st.divider()
    # Current Element Info
    st.markdown(
        f"<h3 style='text-align: center; direction: rtl'>{current['name']}</h3>",
        unsafe_allow_html=True
    )

    type_part = f"<strong>النوع:</strong> {current['type']}"
    definition_part = f"&nbsp; | &nbsp; <strong>الشرح:</strong> {current['definition']}" if type(current.get("definition")) == str and current.get("definition") != "" else ""
    st.markdown(
        f"<p style='text-align: right; direction: rtl'>{type_part} {definition_part}</p>",
        unsafe_allow_html=True
    )

    # Edit current element
    with st.expander("✏️ تعديل هذا العنصر", expanded=False):
        with st.form(f"edit_form_{current_id}"):
            new_name = st.text_input("🏷️ الاسم الجديد", value=current["name"], key=f"edit_name_{current_id}")
            
            new_def = current["definition"] if current["type"] == "مدخل" else ""
            if current["type"] == "مدخل":
                new_def = st.text_area("📖 الشرح الجديد", value=new_def, key=f"edit_def_{current_id}")

            submitted = st.form_submit_button("💾 حفظ التعديلات")
            if submitted:
                st.session_state["hierarchy"][current_id]["name"] = new_name
                if current["type"] == "مدخل":
                    st.session_state["hierarchy"][current_id]["definition"] = new_def
                st.session_state.show_edit_success = True
                st.rerun()
    # Check if the current element has children
    has_children = any(el.get("parent") == current_id for el in st.session_state["hierarchy"].values())

    # Delete section
    if not has_children:
        if st.button("🗑️ حذف هذا العنصر", key=f"delete_button_{current_id}"):
            parent_id = st.session_state["hierarchy"][current_id]["parents"][0]
            # Remove current_id from its parent's children list
            if parent_id in st.session_state["hierarchy"]:
                parent_children = st.session_state["hierarchy"][parent_id].get("children", [])
                if current_id in parent_children:
                    parent_children.remove(current_id)
            del st.session_state["hierarchy"][current_id]
            st.session_state["current_id"] = parent_id
            st.session_state.show_delete_success = True
            st.rerun()
    else:
        st.markdown("""
        <div style='direction: rtl; text-align: right; background-color: #fff3cd; padding: 10px; border-radius: 5px; color: #856404;'>
            ⚠️ لا يمكن حذف هذا العنصر لأنه يحتوي على عناصر فرعية.
        </div>
        """, unsafe_allow_html=True)

    st.divider()


    ## ⬆️ الأصل
    rtl_subheader("الأصل")
    if current["parents"]:
        for pid in set(current["parents"]):
            if st.button(hierarchy[pid]["name"], key=f"parent_nav_{pid}_{current_id}", use_container_width=True):
                st.session_state["current_id"] = pid
                st.rerun()
    else:
        st.info("لا يوجد أصل لهذا العنصر.")

    st.divider()
    ## 🤝 الإخوة
    rtl_subheader("الإخوة")
    siblings = get_siblings(hierarchy, current_id)
    if siblings:
        for i in range(0, len(siblings), 2):
            cols = st.columns(2)
            for j in range(2):
                if i + j < len(siblings):
                    sid = siblings[i + j]
                    if sid not in hierarchy:
                        continue
                    if cols[j].button(hierarchy[sid]["name"], key=f"sibling_nav_{sid}_{current_id}", use_container_width=True):
                        st.session_state["current_id"] = sid
                        st.rerun()
    else:
        st.info("لا يوجد إخوة لهذا العنصر.")

    # Single "Add Sibling" button
    parent_id_for_sibling = current["parents"][0] if current["parents"] else None
    if parent_id_for_sibling:
        render_add_form("أخ", parent_id_for_sibling, infer_type("sibling", current["type"]), f"{current_id}_sibling_add")

    st.divider()
    ## ⬇️ الأبناء
    rtl_subheader("الأبناء")
    if current["children"]:
        for i in range(0, len(current["children"]), 2):
            cols = st.columns(2)
            for j in range(2):
                if i + j < len(current["children"]):
                    cid = current["children"][i + j]
                    if cid not in hierarchy:
                        continue
                    print(cid)
                    if cols[j].button(hierarchy[cid]["name"], key=f"child_nav_{cid}_{current_id}", use_container_width=True):
                        st.session_state["current_id"] = cid
                        st.rerun()
    else:
        st.info("لا يوجد أبناء لهذا العنصر.")

    # Single "Add Child" button
    if current["type"] != "مدخل":
        render_add_form("ابن", current_id, infer_type("child", current["type"]), f"{current_id}_child_add")
        if infer_type("child", current["type"]) == "مدخل":
            render_batch_madkhal_form(current_id, f"{current_id}_batch_add")
    else:
        st.info("لا يمكن إضافة ابن إلى مدخل.")
    
    st.divider()
    ## 💾 تصدير البيانات
    rtl_subheader("💾 تصدير البيانات")
    export_df = export_to_csv(hierarchy)

    # Write to in-memory Excel file
    excel_bytes = io.BytesIO()
    export_df.to_excel(excel_bytes, index=False, engine="openpyxl")
    excel_bytes.seek(0)  # Reset pointer to the beginning of the file

    if st.download_button(
            label="⬇️ تحميل كملف Excel",
            data=excel_bytes,
            file_name="hierarchy.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ):
        st.toast("📤 تم تصدير الملف بنجاح!", icon="✅")
    
    st.divider()
else:
    st.info("يرجى تحميل ملف CSV لبدء العمل.")