#include "visp/vision.h"
#include "util/math.h"
#include "util/string.h"

namespace visp {

model_family model_detect_family(model_file const& file)
{
    if (file.arch() == "birefnet") return model_family::birefnet;
    return model_family::count;
}

birefnet_model birefnet_load_model(char const *filepath, backend_device const &dev)
{
    birefnet_model model;
    model.backend = &dev;
    model_file file = model_load(filepath);
    model.params = birefnet_detect_params(file, {1024, 1024});
    model.weights = model_init(file.n_tensors());
    model_transfer(file, model.weights, dev, dev.preferred_float_type(), dev.preferred_layout());
    return model;
}

image_data birefnet_compute(birefnet_model &model, image_view image)
{
    i32x2 res = birefnet_image_extent(image.extent, model.params, model.backend->max_alloc());
    if (!model.graph || res != model.params.image_extent) {
        model.params.image_extent = res;
        model.graph = compute_graph_init(6 * 1024);

        model_ref m(model.weights, model.graph);
        birefnet_buffers buffers = birefnet_precompute(m, model.params);
        model.input = compute_graph_input(m, GGML_TYPE_F32, {3, res[0], res[1], 1});
        model.output = birefnet_predict(m, model.input, model.params);

        compute_graph_allocate(model.graph, *model.backend);
        for (tensor_data const &buffer : buffers) transfer_to_backend(buffer);
    }

    image_data input = birefnet_process_input(image, model.params);
    transfer_to_backend(model.input, input);
    compute(model.graph, *model.backend);

    tensor_data output = transfer_from_backend(model.output);
    return birefnet_process_output(output.as_f32(), image.extent, model.params);
}

} // namespace visp
