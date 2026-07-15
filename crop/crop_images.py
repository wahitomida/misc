from PIL import Image
from pathlib import Path
import numpy as np
from datetime import datetime

# 設定
INPUT_DIR = Path('/Users/hitomiwada/Dropbox/sample/images')
OUTPUT_DIR = INPUT_DIR / 'cropped'
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920

# 出力ディレクトリを作成
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# RGB値のカウント辞書を初期化
color_counts = {'R': 0, 'G': 0, 'B': 0}

# 画像ファイルの一覧を取得
image_suffixes = {'.jpg', '.jpeg', '.png', '.bmp', '.gif'}
image_files = [f for f in INPUT_DIR.iterdir() 
               if f.is_file() and f.suffix.lower() in image_suffixes]

print(f"処理対象画像数: {len(image_files)}")

for i, filepath in enumerate(sorted(image_files)):
    filename = filepath.name
    
    try:
        # 画像を読み込み
        img = Image.open(filepath).convert('RGB')
        
        width, height = img.size
        
        # 中心座標を計算
        center_x = width // 2
        center_y = height // 2
        
        # 9:16の比率でトリミング領域を計算
        # どちらが制限となるか判定
        aspect_ratio = 9 / 16  # 幅:高さ = 9:16
        
        # 幅基準で計算した場合の高さ
        crop_width = min(width, int(height * aspect_ratio))
        crop_height = int(crop_width / aspect_ratio)
        
        # 高さ基準で計算した場合の幅
        if crop_height > height:
            crop_height = height
            crop_width = int(crop_height * aspect_ratio)
        
        # 中心基準でトリミング領域を計算
        left = max(0, center_x - crop_width // 2)
        top = max(0, center_y - crop_height // 2)
        right = min(width, left + crop_width)
        bottom = min(height, top + crop_height)
        
        # 画像の端に到達した場合は反対側で調整
        if right - left < crop_width:
            if left > 0:
                left = max(0, width - crop_width)
            else:
                right = min(width, crop_width)
        
        if bottom - top < crop_height:
            if top > 0:
                top = max(0, height - crop_height)
            else:
                bottom = min(height, crop_height)
        
        # トリミング実行
        cropped_img = img.crop((left, top, right, bottom))
        
        # 1080×1920にリサイズ
        resized_img = cropped_img.resize((TARGET_WIDTH, TARGET_HEIGHT), Image.Resampling.LANCZOS)
        
        # RGB値を計算
        img_array = np.array(resized_img)
        r_avg = np.mean(img_array[:, :, 0])
        g_avg = np.mean(img_array[:, :, 1])
        b_avg = np.mean(img_array[:, :, 2])
        
        # 最も大きい値を判定
        max_val = max(r_avg, g_avg, b_avg)
        if max_val == r_avg:
            color = 'R'
        elif max_val == g_avg:
            color = 'G'
        else:
            color = 'B'
        
        # カウントを増加
        color_counts[color] += 1
        count_str = f"{color_counts[color]:03d}"
        
        # 保存ファイル名を生成
        output_filename = f"{color}_{count_str}_{datetime.now().strftime('%d%H%M')}.png"
        output_path = OUTPUT_DIR / output_filename
        
        # 画像を保存
        resized_img.save(output_path)
        
        print(f"[{i+1}/{len(image_files)}] {filename}")
        print(f"  → {output_filename} (R:{r_avg:.1f}, G:{g_avg:.1f}, B:{b_avg:.1f})")
        
    except Exception as e:
        print(f"[エラー] {filename} - {str(e)}")

print("\n処理完了!")
print(f"R: {color_counts['R']}, G: {color_counts['G']}, B: {color_counts['B']}")
