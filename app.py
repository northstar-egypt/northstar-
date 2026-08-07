import streamlit as st
import numpy as np
from scipy.ndimage import (
    median_filter,
    uniform_filter,
    minimum_filter,
    maximum_filter,
    gaussian_filter,
    convolve
)
from skimage.filters import sobel, threshold_otsu, threshold_local
from skimage.morphology import dilation, erosion, opening, closing
from skimage.exposure import equalize_hist
from skimage.feature import canny
from skimage.restoration import denoise_bilateral
from skimage.transform import resize
from PIL import Image
from io import BytesIO
import matplotlib.pyplot as plt

# =========================
# PAGE
# =========================
st.set_page_config(layout="wide")
st.title("🎨 IMAGE PROCESSING STUDIO")

# =========================
# SESSION
# =========================
if "original" not in st.session_state:
    st.session_state.original = None

if "processed" not in st.session_state:
    st.session_state.processed = None

if "history" not in st.session_state:
    st.session_state.history = []

if "is_grayscale" not in st.session_state:
    st.session_state.is_grayscale = False


# =========================
# FUNCTIONS
# =========================
def rgb_to_gray(img):
    if len(img.shape) == 2:
        return img
    return np.mean(img, axis=2).astype(np.uint8)


def save_to_history():
    st.session_state.history.append(
        st.session_state.processed.copy()
    )
    if len(st.session_state.history) > 10:
        st.session_state.history.pop(0)


def undo_last():
    if len(st.session_state.history) > 0:
        st.session_state.processed = st.session_state.history.pop()
        st.session_state.is_grayscale = (
            len(st.session_state.processed.shape) == 2
        )


def ensure_gray():
    save_to_history()

    if not st.session_state.is_grayscale:
        st.session_state.processed = rgb_to_gray(
            st.session_state.processed
        )
        st.session_state.is_grayscale = True

    return st.session_state.processed


def apply_filter_rgb(img, func, *args):
    if len(img.shape) == 2:
        return func(img, *args)

    return np.stack(
        [func(img[:, :, i], *args) for i in range(3)],
        axis=2
    )


def compute_snr(original, processed):
    o = rgb_to_gray(original).astype(np.float32)
    p = rgb_to_gray(processed).astype(np.float32)

    num = np.sum(o ** 2)
    den = np.sum((o - p) ** 2) + 1e-10

    return 10 * np.log10(num / den)


# =========================
# SIDEBAR
# =========================
with st.sidebar:

    st.header("📂 Load Image")

    uploaded = st.file_uploader(
        "Choose image",
        type=["png", "jpg", "jpeg"]
    )

    # load once only
    if uploaded and st.session_state.original is None:
        img = np.array(Image.open(uploaded))

        max_size = 1024
        h, w = img.shape[:2]

        if max(h, w) > max_size:
            scale = max_size / max(h, w)

            nw = int(w * scale)
            nh = int(h * scale)

            img = resize(
                img,
                (nh, nw),
                preserve_range=True
            ).astype(np.uint8)

            st.info(f"Resized to {nw}x{nh}")

        st.session_state.original = img
        st.session_state.processed = img.copy()
        st.session_state.history = []
        st.session_state.is_grayscale = (
            len(img.shape) == 2
        )

        st.success("Loaded!")

    if st.session_state.original is not None:

        st.markdown("---")

        if st.button("🔄 RESET"):
            st.session_state.processed = (
                st.session_state.original.copy()
            )
            st.session_state.history = []
            st.session_state.is_grayscale = (
                len(st.session_state.original.shape) == 2
            )
            st.rerun()

        if st.button("↩️ UNDO"):
            undo_last()
            st.rerun()

        st.markdown("---")

        if st.button("🌫️ Convert to Gray"):
            save_to_history()
            st.session_state.processed = rgb_to_gray(
                st.session_state.processed
            )
            st.session_state.is_grayscale = True

        kernel = st.slider(
            "Kernel",
            3,
            11,
            3,
            step=2
        )

        sigma = st.slider(
            "Sigma",
            0.5,
            2.0,
            1.0
        )

        # ================= BASIC =================
        st.markdown("---")
        st.subheader("Basic")

        if st.button("Negative"):
            save_to_history()
            st.session_state.processed = (
                255 - st.session_state.processed
            )

        if st.button("Add +50"):
            save_to_history()
            x = st.session_state.processed.astype(np.int16) + 50
            st.session_state.processed = np.clip(
                x, 0, 255
            ).astype(np.uint8)

        if st.button("Subtract -50"):
            save_to_history()
            x = st.session_state.processed.astype(np.int16) - 50
            st.session_state.processed = np.clip(
                x, 0, 255
            ).astype(np.uint8)

        # ================= SMOOTH =================
        st.markdown("---")
        st.subheader("Smoothing")

        if st.button("Mean"):
            save_to_history()
            st.session_state.processed = apply_filter_rgb(
                st.session_state.processed,
                uniform_filter,
                kernel
            ).astype(np.uint8)

        if st.button("Median"):
            save_to_history()
            st.session_state.processed = apply_filter_rgb(
                st.session_state.processed,
                median_filter,
                kernel
            )

        if st.button("Gaussian"):
            save_to_history()
            x = apply_filter_rgb(
                st.session_state.processed,
                gaussian_filter,
                sigma
            )

            st.session_state.processed = np.clip(
                x, 0, 255
            ).astype(np.uint8)

        # ================= SHARP =================
        st.markdown("---")
        st.subheader("Sharpen")

        if st.button("Sharpen"):
            img = ensure_gray()

            k = np.array([
                [0, -1, 0],
                [-1, 5, -1],
                [0, -1, 0]
            ])

            x = convolve(
                img.astype(np.float32),
                k
            )

            st.session_state.processed = np.clip(
                x, 0, 255
            ).astype(np.uint8)

        # ================= HIST =================
        st.markdown("---")
        st.subheader("Histogram")

        if st.button("Equalization"):
            img = ensure_gray()
            st.session_state.processed = (
                equalize_hist(img) * 255
            ).astype(np.uint8)

        if st.button("Show Histogram"):
            img = rgb_to_gray(
                st.session_state.processed
            )

            fig, ax = plt.subplots()
            ax.hist(img.ravel(), bins=256)
            st.pyplot(fig)
            plt.close()

        # ================= SEGMENT =================
        st.markdown("---")
        st.subheader("Segmentation")

        if st.button("Otsu"):
            img = ensure_gray()
            t = threshold_otsu(img)

            st.session_state.processed = (
                (img >= t) * 255
            ).astype(np.uint8)

        if st.button("Adaptive"):
            img = ensure_gray()
            t = threshold_local(img, 11)

            st.session_state.processed = (
                (img > t) * 255
            ).astype(np.uint8)

        # ================= EDGE =================
        st.markdown("---")
        st.subheader("Edges")

        if st.button("Sobel"):
            img = ensure_gray()
            x = sobel(img)

            st.session_state.processed = (
                x * 255
            ).astype(np.uint8)

        if st.button("Canny"):
            img = ensure_gray()
            x = canny(img)

            st.session_state.processed = (
                x * 255
            ).astype(np.uint8)

        # ================= MORPH =================
        st.markdown("---")
        st.subheader("Morphology")

        se = np.ones((kernel, kernel))

        if st.button("Dilation"):
            img = ensure_gray()
            st.session_state.processed = dilation(img, se)

        if st.button("Erosion"):
            img = ensure_gray()
            st.session_state.processed = erosion(img, se)

        if st.button("Opening"):
            img = ensure_gray()
            st.session_state.processed = opening(img, se)

        if st.button("Closing"):
            img = ensure_gray()
            st.session_state.processed = closing(img, se)

        # ================= BILATERAL =================
        st.markdown("---")
        st.subheader("Bilateral")

        bilateral_sigma = st.slider(
            "Bilateral Sigma",
            0.05,
            0.3,
            0.1
        )

        if st.button("Apply Bilateral"):

            img = ensure_gray()
            h, w = img.shape

            with st.spinner("Applying Bilateral..."):

                if max(h, w) > 500:

                    scale = 500 / max(h, w)

                    nh = int(h * scale)
                    nw = int(w * scale)

                    small = resize(
                        img,
                        (nh, nw),
                        preserve_range=True
                    ).astype(np.uint8)

                    filtered = denoise_bilateral(
                        small,
                        sigma_color=bilateral_sigma,
                        sigma_spatial=15,
                        channel_axis=None
                    )

                    filtered = resize(
                        filtered,
                        (h, w),
                        preserve_range=True
                    )

                else:
                    filtered = denoise_bilateral(
                        img,
                        sigma_color=bilateral_sigma,
                        sigma_spatial=15,
                        channel_axis=None
                    )

                st.session_state.processed = (
                    filtered * 255
                ).astype(np.uint8)

        # ================= NOISE =================
        st.markdown("---")
        st.subheader("Noise")

        if st.button("Salt & Pepper"):
            save_to_history()

            noisy = st.session_state.processed.copy()

            num = int(
                0.05 * noisy.shape[0] * noisy.shape[1]
            )

            rows = np.random.randint(
                0, noisy.shape[0], num
            )
            cols = np.random.randint(
                0, noisy.shape[1], num
            )

            if len(noisy.shape) == 3:
                noisy[rows, cols, :] = 255

                rows2 = np.random.randint(
                    0, noisy.shape[0], num
                )
                cols2 = np.random.randint(
                    0, noisy.shape[1], num
                )
                noisy[rows2, cols2, :] = 0
            else:
                noisy[rows, cols] = 255

            st.session_state.processed = noisy

        if st.button("Remove Noise"):
            save_to_history()
            st.session_state.processed = apply_filter_rgb(
                st.session_state.processed,
                median_filter,
                3
            )

        if st.button("Compute SNR"):
            snr = compute_snr(
                st.session_state.original,
                st.session_state.processed
            )
            st.success(f"SNR = {snr:.2f} dB")


# =========================
# MAIN
# =========================
if st.session_state.original is None:
    st.info("Upload image first")

else:
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Before")
        st.image(
            st.session_state.original,
            use_container_width=True
        )

    with c2:
        st.subheader("After")
        st.image(
            st.session_state.processed,
            use_container_width=True
        )

    st.markdown("---")

    buf = BytesIO()

    Image.fromarray(
        st.session_state.processed
    ).save(
        buf,
        format="PNG"
    )

    st.download_button(
        "💾 Download",
        buf.getvalue(),
        "result.png",
        "image/png"
    )