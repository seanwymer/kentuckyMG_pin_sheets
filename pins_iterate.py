import os
import requests
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import streamlit as st
from io import BytesIO
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import tempfile

def authenticate_and_fetch_events(cookie):
    headers = {
        'Cookie': cookie,
        'User-Agent': 'Mozilla/5.0'
    }
    response = requests.get("https://www.golf-iq.net/api/tournaments", headers=headers)
    st.write("Status Code:", response.status_code)  # Log the HTTP status code
    if response.status_code == 200:
        try:
            data = response.json()  # Parse the JSON response
            if isinstance(data, dict) and "tournaments" in data:
                tournaments = data["tournaments"]
                events = []
                for event in tournaments:
                    for round_info in event.get("rounds", []):
                        events.append({
                            "tournament_id": event.get("id"),
                            "event_name": event.get("name"),
                            "start_date": event.get("start_date"),
                            "course_id": event.get("course", {}).get("id"),
                            "course_name": event.get("course", {}).get("name"),
                            "round_id": round_info.get("id"),
                            "round_name": f"{round_info.get('name')}"
                        })
                return pd.DataFrame(events), headers
            else:
                st.error("Unexpected response format. Expected tournaments data.")
                return None, None
        except Exception as e:
            st.error(f"Error parsing response JSON: {e}")
            return None, None
    else:
        st.error(f"Failed to authenticate or fetch events. Status Code: {response.status_code}")
        return None, None

def get_course_data(round_id, headers, round_name, base_url="https://www.golf-iq.net/api"):
    """Fetch initial course/hole data including image URLs"""
    try:
        response = requests.get(
            f"{base_url}/rounds/{round_id}",
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Extract hole information into DataFrame from the greens array
            holes = []
            for hole in data["round"]["greens"]:
                holes.append({
                    'green_id': hole['id'],
                    'name': hole['name'],
                    'hole_number': hole['name'].split()[-1],  # Extracts number from "Hole X"
                    'image_url': hole['image']['url'],
                    'round_id': round_id,
                    'round_name': round_name
                })
            
            holes_data = pd.DataFrame(holes)
            # st.write(f"Successfully fetched data for {len(holes)} holes")
            return holes_data
        else:
            st.error(f"Failed to fetch course data: {response.status_code}")
            return None
            
    except Exception as e:
        st.error(f"Error fetching course data: {e}")
        return None

def get_green_configurations(round_id, holes_data, headers, base_url="https://www.golf-iq.net/api"):
    """Fetch green configurations for each hole"""
    try:
        # Only add the column if it does not already exist
        if 'green_config' not in holes_data.columns:
            holes_data['green_config'] = None
        
        # st.write("Fetching green configurations...")
        
        for index, row in holes_data.iterrows():
            url = f"{base_url}/green_configurations/{round_id}/{row['green_id']}"
            ## st.write(f"Fetching data for Hole {row['hole_number']} (URL: {url})")
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                config_data = response.json()
                holes_data.at[index, 'green_config'] = config_data
                if 'green_configuration' in config_data:
                    gc = config_data['green_configuration']
                    # st.write(f"Hole {row['hole_number']} data received:")
                    # st.write(f"- Hole Location: {'Present' if gc.get('hole_location') else 'Missing'}")
                    # st.write(f"- Approach: {'Present' if gc.get('approach') else 'Missing'}")
                    # st.write(f"- Go For: {'Present' if gc.get('go_for') else 'Missing'}")
                    # st.write(f"- Crosshairs: {'Present' if gc.get('crosshairs') else 'Missing'}")
                else:
                    st.warning(f"Key 'green_configuration' not found in response for Hole {row['hole_number']}")
            else:
                st.error(f"Failed to fetch configuration for Hole {row['hole_number']}: {response.status_code}")
        
        successful_configs = holes_data['green_config'].notna().sum()
        # st.write(f"Summary: {successful_configs}/{len(holes_data)} configurations fetched successfully.")
        # st.write("### Updated Course Data with Green Configurations")
        # st.dataframe(holes_data)
        
    except Exception as e:
        st.error(f"Error fetching green configurations: {e}")
        return None

def download_green_images(holes_data, output_folder="downloads"):
    """Download green images using URLs from DataFrame"""
    os.makedirs(output_folder, exist_ok=True)
    images = []
    for index, row in holes_data.iterrows():
        filename = f"steelwood-{row['hole_number']}.jpg"
        file_path = os.path.join(output_folder, filename)
        
        try:
            response = requests.get(row['image_url'])
            if response.status_code == 200:
                with open(file_path, 'wb') as file:
                    file.write(response.content)
                # st.write(f"Downloaded image for hole {row['hole_number']} to {file_path}")
                images.append(file_path)
            else:
                st.error(f"Failed to download image for hole {row['hole_number']}")
        except Exception as e:
            st.error(f"Error downloading image for hole {row['hole_number']}: {e}")
    
    return images

def draw_90_degree_lines(image, config):
    """Draw lines on image based on green configuration"""
    draw = ImageDraw.Draw(image)
    
    green_config = config['green_configuration']
    img_width, img_height = image.size

    # Extract data from the JSON
    hole_location = green_config['hole_location']
    approach = green_config.get('approach')
    go_for = green_config.get('go_for')
    crosshairs = green_config.get('crosshairs')

    # Always draw the hole location (pin)
    if hole_location and hole_location.get('origin'):
        hole_x = float(hole_location['origin']['x']) * img_width
        hole_y = float(hole_location['origin']['y']) * img_height
        draw.ellipse((hole_x-5, hole_y-5, hole_x+5, hole_y+5), fill="black")

    # Draw approach lines
    if approach and approach.get('origin') and approach.get('extent'):
        approach_x1 = float(approach['origin']['x']) * img_width
        approach_y1 = float(approach['origin']['y']) * img_height
        approach_x2 = float(approach['extent']['x']) * img_width
        approach_y2 = float(approach['extent']['y']) * img_height
        x_start, x_end = min(approach_x1, approach_x2), max(approach_x1, approach_x2)
        y_start, y_end = min(approach_y1, approach_y2), max(approach_y1, approach_y2)
        draw.line([(approach_x1, y_start), (approach_x1, y_end)], fill="green", width=3)
        draw.line([(x_start, approach_y1), (x_end, approach_y1)], fill="green", width=3)

    # Draw go_for lines
    if go_for and go_for.get('origin') and go_for.get('extent'):
        go_for_x1 = float(go_for['origin']['x']) * img_width
        go_for_y1 = float(go_for['origin']['y']) * img_height
        go_for_x2 = float(go_for['extent']['x']) * img_width
        go_for_y2 = float(go_for['extent']['y']) * img_height
        x_start, x_end = min(go_for_x1, go_for_x2), max(go_for_x1, go_for_x2)
        y_start, y_end = min(go_for_y1, go_for_y2), max(go_for_y1, go_for_y2)
        draw.line([(int(go_for_x1), int(y_start)), (int(go_for_x1), int(y_end))], fill="orange", width=3)
        draw.line([(int(x_start), int(go_for_y1)), (int(x_end), int(go_for_y1))], fill="orange", width=3)

    # Draw crosshairs
    if crosshairs and crosshairs.get('origin') and crosshairs.get('extent'):
        origin_x = float(crosshairs['origin']['x']) * img_width
        origin_y = float(crosshairs['origin']['y']) * img_height
        extent_x = float(crosshairs['extent']['x']) * img_width
        extent_y = float(crosshairs['extent']['y']) * img_height
        x_start, x_end = min(origin_x, extent_x), max(origin_x, extent_x)
        y_start, y_end = min(origin_y, extent_y), max(origin_y, extent_y)
        center_x = (x_start + x_end) / 2
        center_y = (y_start + y_end) / 2
        radius = min(x_end - x_start, y_end - y_start) / 2

        draw.ellipse([int(center_x - radius), int(center_y - radius), 
                      int(center_x + radius), int(center_y + radius)], 
                     outline="red", width=2)
        draw.line([int(x_start), int(center_y), int(x_end), int(center_y)], fill="red", width=2)
        draw.line([int(center_x), int(y_start), int(center_x), int(y_end)], fill="red", width=2)

    return image

def process_images_with_configurations(holes_data, output_folder):
    """Process images and add green configurations to them"""
    processed_images = []
    for index, row in holes_data.iterrows():
        file_path = os.path.join(output_folder, f"steelwood-{row['hole_number']}.jpg")
        if os.path.exists(file_path) and row['green_config']:
            try:
                image = Image.open(file_path)
                config = row['green_config']
                updated_image = draw_90_degree_lines(image, config)
                buffer = BytesIO()
                updated_image.save(buffer, format="JPEG")
                buffer.seek(0)
                processed_images.append(buffer)
            except Exception as e:
                st.error(f"Error processing image for hole {row['hole_number']}: {e}")
        else:
            processed_images.append(None)
    
    holes_data['processed_image'] = processed_images
    return holes_data

def create_grid_image(images, hole_numbers, grid_size=3, margin_size=20):
    """Create a grid image with specified hole numbers in column-first order:
    1 4 7
    2 5 8
    3 6 9
    """
    # Get dimensions from the first valid image
    valid_images = [img for img in images if img is not None]
    if not valid_images:
        st.error("No valid images to create a grid.")
        return None

    image_width, image_height = valid_images[0].size
    grid_image_width = image_width * grid_size + margin_size * (grid_size + 1)
    grid_image_height = image_height * grid_size + margin_size * (grid_size + 1)

    # Create a blank canvas for the grid
    grid_image = Image.new('RGB', (grid_image_width, grid_image_height), 'white')
    draw = ImageDraw.Draw(grid_image)
    
     # Load a font for the hole numbers
    try:
        # Try multiple font options
        for font_name in ["Arial Bold", "DejaVuSans-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
            try:
                font = ImageFont.truetype(font_name, 30)
                # st.write(f"Successfully loaded font: {font_name}")
                break
            except:
                continue
    except:
        # st.write("Falling back to default font")
        font = ImageFont.load_default()

    # Draw each image into the grid
    for idx, hole_number in enumerate(hole_numbers):
        # Calculate position in column-first order
        col = idx // grid_size  # Integer division for column
        row = idx % grid_size   # Remainder for row

        x_position = margin_size + col * (image_width + margin_size)
        y_position = margin_size + row * (image_height + margin_size)

        # For back 9, adjust the index to account for the offset
        image_idx = hole_number - 1 if hole_number <= 9 else hole_number - 10
        
        if image_idx < len(images) and images[image_idx]:
            grid_image.paste(images[image_idx], (x_position, y_position))
            
            # Add hole number in the top-left corner of each image
            number_margin = 20
            text_position = (x_position + number_margin, y_position + number_margin)
            
            # Draw white background circle for better visibility
            circle_radius = 30
            circle_bbox = (
                text_position[0] - circle_radius,
                text_position[1] - circle_radius,
                text_position[0] + circle_radius,
                text_position[1] + circle_radius
            )
            draw.ellipse(circle_bbox, fill='white', outline='black', width=3)
            
            # Draw the hole number
            text = str(hole_number)
            # Get text size for centering in circle
            text_bbox = draw.textbbox(text_position, text, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]
            
            # Center text in circle
            text_x = text_position[0] - text_width/2
            text_y = text_position[1] - text_height/2 - 8  # Subtract more pixels to move up
            draw.text((text_x, text_y), text, fill='black', font=font)

    return grid_image

def create_pdf_with_grids(front_grid, back_grid, event_name, course_name, round_name, date, output_path="pin_sheet.pdf"):
    """Create a PDF with front nine grid on first page and back nine grid on second page"""
    # First convert PIL images to bytes
    front_buffer = BytesIO()
    back_buffer = BytesIO()
    front_grid.save(front_buffer, format='PNG')
    back_grid.save(back_buffer, format='PNG')
    
    # Create PDF
    c = canvas.Canvas(output_path, pagesize=letter)
    
    # Get page dimensions
    page_width, page_height = letter
    
    # Set up text parameters
    left_margin = 25
    right_margin = page_width - 25
    top_margin = page_height - 25
    line_height = 20
    
    def add_header_text(canvas):
        # Primary text (bold)
        canvas.setFont("Helvetica-Bold", 14)
        canvas.drawString(left_margin, top_margin, event_name)
        round_text_width = canvas.stringWidth(round_name, "Helvetica-Bold", 14)
        canvas.drawString(right_margin - round_text_width, top_margin, round_name)
        
        # Secondary text (regular, smaller)
        canvas.setFont("Helvetica", 12)
        canvas.drawString(left_margin, top_margin - line_height, course_name)
        date_text_width = canvas.stringWidth(date, "Helvetica", 12)
        canvas.drawString(right_margin - date_text_width, top_margin - line_height, date)
    
    # Calculate scaling and positioning to fit the images on the pages
    margin = 25
    top_text_space = 50  # Space for header text
    available_width = page_width - 2 * margin
    available_height = page_height - 2 * margin - top_text_space
    
    # Calculate scale factor to fit image within available space
    front_width, front_height = front_grid.size
    scale_factor = min(available_width/front_width, available_height/front_height)
    
    # Calculate centered position
    x_centered = margin + (available_width - front_width * scale_factor) / 2
    y_centered = margin + (available_height - front_height * scale_factor) / 2
    
    # Draw front nine page
    add_header_text(c)
    c.drawImage(ImageReader(BytesIO(front_buffer.getvalue())),
                x_centered, y_centered,
                width=front_width * scale_factor,
                height=front_height * scale_factor)
    c.showPage()
    
    # Draw back nine page
    add_header_text(c)
    c.drawImage(ImageReader(BytesIO(back_buffer.getvalue())),
                x_centered, y_centered,
                width=front_width * scale_factor,
                height=front_height * scale_factor)
    c.showPage()
    
    c.save()
    return output_path

st.title("Kentucky Men's Golf Pin Sheets")

cookie = '_rails_app_session=VDU2eFcxMk1WT3pUL1JmUG9XU25pSWJVbEg2aEJvU2gwbGpzYTlmK0p2UElHalVrelFpRWQ3MGg1alRpMlNXZ1dRck1PTlQzN2ZFVDRzZXB2L0dRdU5HRWhXQ08xNEtVSU1TK3hWN2xUUUhTell3dXhYUzdlbUJYWEpYZjVzVm1PaDBBcGtabkg4WFlRODZXT3J6RXRhNlRSZkJ4b0hKVzhRdWFjcDF3MGVYQkNsYVZRa1RHN2Qxc0htOXI5M1crREdNMlM3OVo3aUFYTys0Nmg0UGpITW9EQjZRalk1TnVueFpqWFdlM0Y0RHJ3M00vTHMzNnlOREptNDFXOGsvTC0tbU1CVm9EcVcwZ25qcStjM0hjbU1oUT09--acf6a1944c6f787f5416da085bbfdcbd6262fdf8; path=/; secure; HttpOnly'  # Replace with actual cookie

output_folder = "downloads"
event_df, headers = authenticate_and_fetch_events(cookie)

if event_df is not None:
    st.write("### List of Events")
    
    # Create a container for the status messages and download button
    status_container = st.empty()
    download_container = st.empty()
    
    # Create headers for the columns
    header_cols = st.columns([2, 1, 1, 1, 1])
    header_cols[0].write("**Event Name**")
    header_cols[1].write("**Date**")
    header_cols[2].write("**Course**")
    header_cols[3].write("**Round**")
    header_cols[4].write("**Action**")
    
    # Create a container for each row
    for _, row in event_df.iterrows():
        col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])
        
        with col1:
            st.write(row['event_name'])
        with col2:
            st.write(row['start_date'])
        with col3:
            st.write(row['course_name'])
        with col4:
            st.write(row['round_name'])
        with col5:
            if st.button('Generate PDF', key=f"btn_{row['round_id']}"):
                # Clear previous status/download
                status_container.empty()
                download_container.empty()
                
                with status_container:
                    with st.spinner('Processing pin sheet data...'):
                        holes_data = get_course_data(row['round_id'], headers, row['round_name'])
                        if holes_data is not None:
                            # Fetch and add green configurations
                            get_green_configurations(row['round_id'], holes_data, headers)

                            # Download green images
                            download_green_images(holes_data, output_folder)

                            # Process images with configurations
                            holes_data = process_images_with_configurations(holes_data, output_folder)
                            
                            holes_data = holes_data.iloc[::-1]

                            # Get all processed images
                            processed_images = []
                            for img in holes_data['processed_image']:
                                if img:
                                    processed_images.append(Image.open(BytesIO(img.getvalue())))
                                else:
                                    processed_images.append(None)

                            # Create 3x3 grids for front 9 and back 9
                            front_nine = processed_images[:9]
                            back_nine = processed_images[9:]

                            # Create grids and PDF
                            if front_nine and back_nine:
                                front_grid = create_grid_image(front_nine, range(1, 10), grid_size=3)
                                back_grid = create_grid_image(back_nine, range(10, 19), grid_size=3)
                                
                                if front_grid and back_grid:
                                    pdf_path = create_pdf_with_grids(
                                        front_grid, 
                                        back_grid,
                                        event_name=row['event_name'],
                                        course_name=row['course_name'],
                                        round_name=row['round_name'],
                                        date=row['start_date'],
                                        output_path="pin_sheet.pdf"
                                    )
                                    
                                    st.success('Pin sheet generated successfully!')
                                    
                                    # Create filename from tournament and round name
                                    safe_event_name = row['event_name'].replace(" ", "_").replace("/", "-")
                                    safe_round_name = row['round_name'].replace(" ", "_").replace("/", "-")
                                    pdf_filename = f"{safe_event_name}_{safe_round_name}_pin_sheet.pdf"
                                    
                                    # Create a download button in the separate container
                                    with download_container:
                                        with open(pdf_path, "rb") as pdf_file:
                                            pdf_bytes = pdf_file.read()
                                            st.download_button(
                                                label="Download Pin Sheet PDF",
                                                data=pdf_bytes,
                                                file_name=pdf_filename,
                                                mime="application/pdf",
                                                key=f"download_{row['round_id']}"
                                            )

## Now populating the green images in the correct order in the grid. They have the correct green_configurations. Now need
## to run the create_pdf and get_position_and_number methods. 