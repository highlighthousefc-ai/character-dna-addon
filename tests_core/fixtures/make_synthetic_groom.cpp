// Writes tests_core/fixtures/synthetic_groom.abc: a tiny groom laid out like Unreal's groom Alembic
// files (the MetaHuman export's Grooms/*.abc), with made-up data. Used by the numpy Ogawa reader tests.
//
// Build with the reference Alembic library (BSD-3), e.g. Homebrew's:
//   clang++ -std=c++17 make_synthetic_groom.cpp -I/opt/homebrew/include -I/opt/homebrew/include/Imath \
//     -L/opt/homebrew/lib -lAlembic -o make_synthetic_groom && ./make_synthetic_groom synthetic_groom.abc
//
// Strands (points in cm, Z up):
//   0: 3 points, rendered            1: 4 points, a guide collapsed at the origin
//   2: 2 points, one negative width  3: 3 points, rendered
#include <Alembic/AbcCoreOgawa/All.h>
#include <Alembic/AbcGeom/All.h>

using namespace Alembic::AbcGeom;

int main(int argc, char** argv) {
    OArchive archive(Alembic::AbcCoreOgawa::WriteArchive(), argc > 1 ? argv[1] : "synthetic_groom.abc");
    OXform groom(archive.getTop(), "Groom");
    OCurves curves(groom, "Curves");
    OCurvesSchema& schema = curves.getSchema();

    std::vector<V3f> points = {
        {1.0f, 2.0f, 150.0f},  {1.5f, 2.5f, 151.0f},  {2.0f, 3.0f, 152.0f},                        // 0
        {0.0f, 0.0f, 0.0f},    {0.0f, 0.0f, 0.0f},    {0.0f, 0.0f, 0.0f},    {0.0f, 0.0f, 0.0f},   // 1 guide
        {-4.0f, 6.0f, 160.0f}, {-4.5f, 6.5f, 161.0f},                                              // 2
        {7.0f, -8.0f, 170.0f}, {7.5f, -8.5f, 171.0f}, {8.0f, -9.0f, 172.0f},                       // 3
    };
    std::vector<int32_t> counts = {3, 4, 2, 3};
    std::vector<float> widths = {0.02f, 0.015f, 0.01f, 0.001f, 0.001f, 0.001f, 0.0f,
                                 -0.0005f, 0.004f, 0.012f, 0.008f, 0.004f};
    std::vector<V2f> root_uvs = {{0.25f, 0.75f}, {0.0f, 0.0f}, {0.5f, 0.5f}, {0.9f, 0.1f}};

    OFloatGeomParam::Sample width_sample(FloatArraySample(widths), kVertexScope);
    OV2fGeomParam::Sample uv_sample(V2fArraySample(root_uvs), kUniformScope);
    OCurvesSchema::Sample sample(V3fArraySample(points), Int32ArraySample(counts), kLinear, kNonPeriodic,
                                 width_sample, uv_sample);
    schema.set(sample);

    OCompoundProperty arb = schema.getArbGeomParams();
    OInt32GeomParam guide(arb, "groom_guide", false, kUniformScope, 1);
    std::vector<int32_t> guides = {0, 1, 0, 0};
    guide.set(OInt32GeomParam::Sample(Int32ArraySample(guides), kUniformScope));
    OV3fGeomParam color(arb, "groom_color", false, kVertexScope, 1);
    std::vector<V3f> colors(points.size(), V3f(0.25f, 0.5f, 0.0f));
    color.set(OV3fGeomParam::Sample(V3fArraySample(colors), kVertexScope));
    return 0;
}
