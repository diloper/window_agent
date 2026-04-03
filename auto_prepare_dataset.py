import os
import shutil
import random

# --- 1. 設定路徑 (請根據你的實際資料夾名稱修改) ---
source_images_dir = "./A"    # 原始圖片存放處
source_labels_dir = "./labels"    # X-AnyLabeling 匯出的 YOLO txt 資料夾
classes_file_path = "./classes.txt"   # 你的類別定義檔
output_base_dir = "./my_dataset"
train_ratio = 0.8  # 80% 訓練, 20% 驗證

# --- 2. 讀取 classes.txt 分析類別 ---
if not os.path.exists(classes_file_path):
    print(f"錯誤: 找不到 {classes_file_path}，請確認檔案路徑！")
    exit()

with open(classes_file_path, 'r', encoding='utf-8') as f:
    # 讀取每一行，去除空白，並過濾掉空行
    class_names = [line.strip() for line in f.readlines() if line.strip()]

num_classes = len(class_names)
print(f"🔍 偵測到 {num_classes} 個類別: {class_names}")

# --- 3. 建立 YOLO 資料夾結構 ---
sub_dirs = ['train/images', 'train/labels', 'val/images', 'val/labels']
for sub_dir in sub_dirs:
    os.makedirs(os.path.join(output_base_dir, sub_dir), exist_ok=True)

# --- 4. 隨機拆分並搬移檔案 ---
image_files = [f for f in os.listdir(source_images_dir) if f.lower().endswith(('.jpg', '.png', '.jpeg'))]
random.shuffle(image_files)

split_idx = int(len(image_files) * train_ratio)
train_files = image_files[:split_idx]
val_files = image_files[split_idx:]

def move_files(file_list, target_type):
    for img_name in file_list:
        # 複製圖片
        shutil.copy(os.path.join(source_images_dir, img_name),
                    os.path.join(output_base_dir, target_type, 'images', img_name))

        # 尋找對應標註檔
        label_name = os.path.splitext(img_name)[0] + ".txt"
        label_path = os.path.join(source_labels_dir, label_name)

        if os.path.exists(label_path):
            shutil.copy(label_path, os.path.join(output_base_dir, target_type, 'labels', label_name))

move_files(train_files, 'train')
move_files(val_files, 'val')

# --- 5. 自動產生符合類別數量的 data.yaml ---
yaml_content = f"""
path: {os.path.abspath(output_base_dir)}
train: train/images
val: val/images

nc: {num_classes}
names: {class_names}
"""

with open(os.path.join(output_base_dir, 'data.yaml'), 'w', encoding='utf-8') as f:
    f.write(yaml_content.strip())

print(f"✅ 成功！已根據 classes.txt 產生含有 {num_classes} 個類別的 data.yaml")
